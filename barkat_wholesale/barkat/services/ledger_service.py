from decimal import Decimal
from datetime import date, timedelta
from typing import Optional, List, Dict, Any, Tuple
from django.db.models import Sum, Q, Prefetch
from django.shortcuts import get_object_or_404

from barkat.models import (
    Business, Party, Staff, Payment, BankMovement,
    SalesOrder, SalesOrderItem, SalesInvoice, SalesInvoiceReceipt, SalesReturn, SalesReturnRefund,
    PurchaseOrder, PurchaseOrderItem, PurchaseOrderPayment, PurchaseReturn, PurchaseReturnRefund,
    Expense, ExpenseCategory
)
from barkat.ledger import LedgerRow, builds_ledger_base # We might need to split ledger.py later

class LedgerService:
    @staticmethod
    def get_ledger_data(
        kind: str,
        entity_id: int,
        business_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Any]:
        """
        Main entry point for fetching unified ledger data.
        Handles both single-business and multi-business (all) modes.
        """
        if kind == "staff":
            return LedgerService._get_staff_ledger(entity_id, business_id, date_from, date_to)
        
        return LedgerService._get_party_ledger(kind, entity_id, business_id, date_from, date_to)

    @staticmethod
    def _get_staff_ledger(staff_id, business_id, date_from, date_to):
        from barkat.ledger import build_ledger
        # Staff ledger is simpler as it's usually tied to one business
        staff = get_object_or_404(Staff, pk=staff_id)
        # If business_id is not provided, use staff.business
        target_biz_id = business_id or staff.business_id
        
        rows, totals, entity = build_ledger(
            kind="staff",
            business_id=target_biz_id,
            entity_id=staff_id,
            date_from=date_from,
            date_to=date_to,
        )
        
        rows_dicts = LedgerService._normalize_rows(rows)
        LedgerService._compute_running_balance(rows_dicts)
        
        return rows_dicts, totals, entity

    @staticmethod
    def _get_party_ledger(kind, party_id, business_id, date_from, date_to):
        party = get_object_or_404(Party, pk=party_id)
        
        biz_ids = []
        if business_id:
            biz_ids = [business_id]
        else:
            biz_ids = list(Business.objects.filter(is_deleted=False, is_active=True).values_list("id", flat=True))

        all_rows = []
        total_dr = Decimal("0.00")
        total_cr = Decimal("0.00")
        
        # 1. Opening Balance Calculation
        open_dr, open_cr = LedgerService._calculate_opening_balance(kind, party, business_id, date_from)
        
        # 2. Add B/F row if needed
        if open_dr != open_cr:
            balance = open_dr - open_cr
            all_rows.append({
                "date": date_from,
                "ref": "B/F",
                "note": "Balance brought forward",
                "dr": balance if balance > 0 else None,
                "cr": -balance if balance < 0 else None,
                "is_opening_row": True,
            })
            total_dr += (balance if balance > 0 else 0)
            total_cr += (-balance if balance < 0 else 0)

        # 3. Transactional Rows from built-in ledger logic (Order/Line Items)
        for b_id in biz_ids:
            from barkat.ledger import build_ledger
            # We use build_ledger to get the "standard" rows (Invoices, Orders, Returns)
            # But we must prevent it from adding its own B/F if we're aggregating
            rows_b, totals_b, _ = build_ledger(
                kind=kind,
                business_id=b_id,
                entity_id=party_id,
                date_from=date_from,
                date_to=date_to,
            )
            # Filter out B/F and Opening from the base ledger as we handle them globally
            cleaned_rows = [r for r in rows_b if getattr(r, 'source', '') not in ('B/F', 'Opening')]
            
            # Filter out pending cheques if needed (following ledger_views logic)
            filtered_rows = LedgerService._filter_cheque_rows(cleaned_rows, b_id, party_id, kind)
            
            biz_name = Business.objects.filter(id=b_id).values_list('name', flat=True).first() or ""
            dict_rows = LedgerService._normalize_rows(filtered_rows, extra={"biz_id": b_id, "biz_name": biz_name})
            
            all_rows.extend(dict_rows)
            for r in dict_rows:
                total_dr += Decimal(str(r.get('dr') or 0))
                total_cr += Decimal(str(r.get('cr') or 0))

        # 4. Standalone Payments (The logic missing from ledger.py)
        payment_rows, p_dr, p_cr = LedgerService._get_standalone_payment_rows(party, biz_ids, kind, date_from, date_to)
        all_rows.extend(payment_rows)
        total_dr += p_dr
        total_cr += p_cr

        # 5. Bank Movements (Cheque payments to suppliers)
        bm_rows, bm_dr, bm_cr = LedgerService._get_bank_movement_rows(party, biz_ids, kind, date_from, date_to)
        all_rows.extend(bm_rows)
        total_dr += bm_dr
        total_cr += bm_cr

        # 6. Sorting and Running Balance
        all_rows.sort(key=lambda x: (x.get("date") or date.min, 0 if x.get("is_opening_row") else 1))
        LedgerService._compute_running_balance(all_rows)

        balance = total_dr - total_cr
        totals = {
            "total_dr": total_dr.quantize(Decimal("0.01")),
            "total_cr": total_cr.quantize(Decimal("0.01")),
            "balance_abs": abs(balance).quantize(Decimal("0.01")),
            "balance_side": "Dr" if balance >= 0 else "Cr",
        }

        return all_rows, totals, party

    @staticmethod
    def _calculate_opening_balance(kind, party, business_id, date_from):
        """
        Calculates the opening balance (including B/F) for a party.
        """
        open_dr = Decimal("0.00")
        open_cr = Decimal("0.00")

        # Static Opening Balance from model
        from barkat.ledger import opening_balance as get_static_ob
        if not date_from:
            # If no date filter, just use the static opening
            ob, side = get_static_ob(kind, party, business_id)
            if side == 'Dr': open_dr = ob
            else: open_cr = ob
        else:
            # If date filter, we need to compute B/F (transactions before date_from) + static opening
            # Relies on the logic in ledger_views._compute_opening_before_date_for_party
            from barkat.ledger_views import _compute_opening_before_date_for_party
            
            biz_list = []
            if business_id:
                biz_list = [Business.objects.get(id=business_id)]
            else:
                biz_list = list(Business.objects.filter(is_deleted=False, is_active=True))
            
            biz_ids = [b.id for b in biz_list]
            open_dr, open_cr = _compute_opening_before_date_for_party(
                kind, party.id, biz_list, biz_ids, date_from
            )
            
        return open_dr, open_cr

    @staticmethod
    def _get_standalone_payment_rows(party, biz_ids, kind, date_from, date_to):
        """
        Fetches payments NOT linked to specific orders.
        Translated from LedgerDetailView._build_payment_rows_for_businesses
        """
        qs = Payment.objects.select_related("business", "bank_account").filter(party_id=party.id)
        
        # Filter out payments applied to orders/returns (they're in ledger.py)
        qs = qs.filter(applied_purchase_orders__isnull=True)
        if hasattr(Payment, "applied_sales_orders"):
            qs = qs.filter(applied_sales_orders__isnull=True)
        elif hasattr(Payment, "sales_orders"):
            qs = qs.filter(sales_orders__isnull=True)
        
        if hasattr(Payment, "applied_sales_returns"):
             qs = qs.filter(applied_sales_returns__isnull=True)
        if hasattr(Payment, "applied_purchase_returns"):
             qs = qs.filter(applied_purchase_returns__isnull=True)

        if biz_ids:
            qs = qs.filter(business_id__in=biz_ids)
        
        if date_from: qs = qs.filter(date__gte=date_from)
        if date_to: qs = qs.filter(date__lte=date_to)

        rows = []
        total_dr = Decimal("0.00")
        total_cr = Decimal("0.00")

        for p in qs:
            # Skip pending cheques as per business rules
            if p.payment_method == Payment.PaymentMethod.CHEQUE and p.cheque_status == Payment.ChequeStatus.PENDING:
                continue
            
            # Skip return/refund payments (already handled by returns logic)
            from barkat.ledger_views import _is_return_refund_payment
            if _is_return_refund_payment(p):
                continue

            amount = p.amount.quantize(Decimal("0.01"))
            dr = Decimal("0.00")
            cr = Decimal("0.00")

            if kind == "customer":
                if p.direction == Payment.IN: cr = amount
                else: dr = amount
            else: # supplier
                if p.direction == Payment.OUT: dr = amount
                else: cr = amount

            rows.append({
                "date": p.date,
                "ref": p.reference or f"PAY-{p.pk}",
                "note": p.description or f"{p.get_payment_method_display()}",
                "dr": dr if dr > 0 else None,
                "cr": cr if cr > 0 else None,
                "biz_id": p.business_id,
                "biz_name": getattr(p.business, "name", ""),
                "is_payment_row": True,
            })
            total_dr += dr
            total_cr += cr

        return rows, total_dr, total_cr

    @staticmethod
    def _get_bank_movement_rows(party, biz_ids, kind, date_from, date_to):
        """
        Fetches BankMovements (mainly cheque payments).
        Translated from LedgerDetailView._build_bankmovement_rows_for_businesses
        """
        qs = BankMovement.objects.select_related("purchase_order", "purchase_order__business", "from_bank").filter(
            movement_type=BankMovement.CHEQUE_PAYMENT, party_id=party.id
        )

        if biz_ids:
            qs = qs.filter(Q(purchase_order__business_id__in=biz_ids) | Q(purchase_order__isnull=True))

        if date_from: qs = qs.filter(date__gte=date_from)
        if date_to: qs = qs.filter(date__lte=date_to)

        rows = []
        total_dr = Decimal("0.00")
        total_cr = Decimal("0.00")

        for mv in qs:
            amount = mv.amount.quantize(Decimal("0.01"))
            
            # For suppliers, movement is a debit
            dr = amount
            cr = Decimal("0.00")

            rows.append({
                "date": mv.date,
                "ref": mv.reference_no or f"CHQ-{mv.id}",
                "note": mv.notes or "Cheque Payment",
                "dr": dr if dr > 0 else None,
                "cr": cr if cr > 0 else None,
                "biz_id": getattr(mv.purchase_order, "business_id", None),
                "biz_name": getattr(getattr(mv.purchase_order, "business", None), "name", ""),
                "is_bankmovement_row": True,
            })
            total_dr += dr
            total_cr += cr

        return rows, total_dr, total_cr

    @staticmethod
    def _filter_cheque_rows(rows, business_id, party_id, kind):
        from barkat.ledger_views import _filter_cheque_payments_from_rows
        return _filter_cheque_payments_from_rows(rows, business_id, party_id, kind, exclude_pending=True)

    @staticmethod
    def _normalize_rows(rows, extra=None):
        out = []
        for r in rows:
            if isinstance(r, dict):
                d = r.copy()
            else:
                d = {
                    "date": getattr(r, "date", None),
                    "ref": getattr(r, "ref", ""),
                    "note": getattr(r, "note", ""),
                    "dr": getattr(r, "dr", None),
                    "cr": getattr(r, "cr", None),
                    "source": getattr(r, "source", ""),
                    "pk": getattr(r, "pk", None),
                }
            if extra:
                d.update(extra)
            out.append(d)
        return out

    @staticmethod
    def _compute_running_balance(rows):
        running = Decimal("0.00")
        for r in rows:
            dr = Decimal(str(r.get("dr") or 0)) if r.get("dr") else Decimal("0.00")
            cr = Decimal(str(r.get("cr") or 0)) if r.get("cr") else Decimal("0.00")
            running = running + dr - cr
            r["run_amount"] = abs(running).quantize(Decimal("0.01"))
            r["run_side"] = "Dr" if running >= 0 else "Cr"
