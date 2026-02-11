from __future__ import annotations

# Standard Library imports
import re
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional
from urllib.parse import urlencode

# Django core imports
from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q, Sum, Case, When, F, Value, DecimalField, Count, ExpressionWrapper
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator

# Django View imports
from django.views import View
from django.views.generic import ListView
from django.views.decorators.http import require_GET

# Local folder/Relative imports
from .ledger import build_ledger
from .utils.auth_helpers import user_has_cancellation_password
from .models import (
    Business, Party, Staff, Payment, Product,
    SalesOrder, SalesOrderItem, 
    PurchaseOrder, PurchaseOrderItem,
    PurchaseReturn, PurchaseReturnItem,  # Ensure these are here
    SalesReturn, SalesReturnItem,        # Ensure these are here
    BankMovement, PurchaseOrderPayment, Expense
)
# =========================
# generic helpers
# =========================

def _parse_date(s: str | None) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _fmt(d: Optional[date]) -> Optional[str]:
    return d.strftime("%Y-%m-%d") if d else None


def _looks_like_opening(ref: str | None, note: str | None) -> bool:

    r = (ref or "").strip().upper()
    n = (note or "").strip().upper()

    tokens = (
        "OPENING",
        "OPENING BALANCE",
        "OPEN BAL",
        "BALANCE B/F",
        "B/F",
        "BALANCE BROUGHT FORWARD",
        "BAL BROUGHT FORWARD",
        "BAL BROT FWD",
    )

    if r in tokens:
        return True
    if any(tok in r for tok in tokens):
        return True
    if any(tok in n for tok in tokens):
        return True
    return False


def _extract_opening(rows):
    """
    Remove any rows that look like opening balance.
    Return (cleaned_rows, opening_dr, opening_cr).
    """
    cleaned = []
    open_dr = Decimal("0.00")
    open_cr = Decimal("0.00")

    for r in rows:
        if isinstance(r, dict):
            ref = r.get("ref")
            note = r.get("note")
            dr = r.get("dr")
            cr = r.get("cr")
        else:
            ref = getattr(r, "ref", None)
            note = getattr(r, "note", None)
            dr = getattr(r, "dr", None)
            cr = getattr(r, "cr", None)

        if _looks_like_opening(ref, note):
            if dr:
                open_dr += Decimal(str(dr))
            if cr:
                open_cr += Decimal(str(cr))
        else:
            cleaned.append(r)

    return cleaned, open_dr, open_cr


def _rows_to_dicts(rows, extra: dict | None = None):
    out = []
    for r in rows:
        d = {
            "date": r.get("date") if isinstance(r, dict) else getattr(r, "date", None),
            "ref": r.get("ref", "") if isinstance(r, dict) else getattr(r, "ref", "") or "",
            "note": r.get("note", "") if isinstance(r, dict) else getattr(r, "note", "") or "",
            "dr": r.get("dr") if isinstance(r, dict) else getattr(r, "dr", None),
            "cr": r.get("cr") if isinstance(r, dict) else getattr(r, "cr", None),
            "source": r.get("source", "") if isinstance(r, dict) else getattr(r, "source", "") or "",
            "allocations": r.get("allocations") if isinstance(r, dict) else getattr(r, "allocations", None),
            "metadata": r.get("metadata") if isinstance(r, dict) else getattr(r, "metadata", None),
            "product_name": r.get("product_name", "") if isinstance(r, dict) else getattr(r, "product_name", "") or "",
            "quantity": r.get("quantity", "") if isinstance(r, dict) else getattr(r, "quantity", "") or "",
            "unit_price": r.get("unit_price", "") if isinstance(r, dict) else getattr(r, "unit_price", "") or "",
        }
        
        # Extract metadata if available
        meta = r.get("metadata") if isinstance(r, dict) else getattr(r, "metadata", None)
        if meta:
            d["payment_method"] = meta.get("payment_method")
            d["bank_name"] = meta.get("bank_name")
            
        if extra:
            d.update(extra)
        out.append(d)
    return out


def _compute_running_balance(rows_dicts):
    running = Decimal("0.00")
    for d in rows_dicts:
        dr = Decimal(str(d["dr"])) if d.get("dr") not in (None, "", "-") else Decimal("0.00")
        cr = Decimal(str(d["cr"])) if d.get("cr") not in (None, "", "-") else Decimal("0.00")
        running = running + dr - cr
        d["run_amount"] = abs(running)
        d["run_side"] = "Dr" if running >= 0 else "Cr"


def _q2_decimal(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value).quantize(Decimal("0.01"))


def _fmt2(value) -> str:
    if value is None:
        return ""
    return f"{_q2_decimal(value):.2f}"


# =========================
# regex helpers for SO PO SR PR
# =========================

_SO_REF_RE = re.compile(r"\bSO\s*#?\s*(\d+)\b", re.IGNORECASE)
_PO_REF_RE = re.compile(r"\bPO\s*#?\s*(\d+)\b", re.IGNORECASE)
_SR_REF_RE = re.compile(r"\bSR\s*#?\s*(\d+)\b", re.IGNORECASE)
_PR_REF_RE = re.compile(r"\bPR\s*#?\s*(\d+)\b", re.IGNORECASE)


def _parse_so_id_from_ref(ref: str | None) -> int | None:
    if not ref:
        return None
    m = _SO_REF_RE.search(ref)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _parse_po_id_from_ref(ref: str | None) -> int | None:
    if not ref:
        return None
    m = _PO_REF_RE.search(ref)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _parse_sr_id_from_ref(ref: str | None) -> int | None:
    if not ref:
        return None
    m = _SR_REF_RE.search(ref)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _parse_pr_id_from_ref(ref: str | None) -> int | None:
    if not ref:
        return None
    m = _PR_REF_RE.search(ref)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _is_return_refund_payment(payment: Payment) -> bool:
    """
    True when this Payment is a refund related to a Sales Return or Purchase Return.
    These should not be added as separate rows on top of the return document.
    This avoids double counting in party ledger.
    
    NOTE: Refund payments are handled separately in ledger.py via SalesReturnRefund
    and PurchaseReturnRefund, so we filter them out from payment rows to avoid duplicates.
    """
    # Check if payment is linked to a SalesReturnRefund (preferred method)
    if hasattr(payment, "applied_sales_returns"):
        try:
            # Use count() instead of exists() to avoid issues with prefetch
            if payment.applied_sales_returns.count() > 0:
                return True
        except Exception:
            # If count fails, try exists() as fallback
            try:
                if payment.applied_sales_returns.exists():
                    return True
            except Exception:
                pass
    
    # Check if payment is linked to a PurchaseReturnRefund
    if hasattr(payment, "applied_purchase_returns"):
        try:
            if payment.applied_purchase_returns.count() > 0:
                return True
        except Exception:
            try:
                if payment.applied_purchase_returns.exists():
                    return True
            except Exception:
                pass
    
    # Legacy checks for direct attributes (may not exist)
    if hasattr(payment, "sales_return_id") and getattr(payment, "sales_return_id"):
        return True
    if hasattr(payment, "purchase_return_id") and getattr(payment, "purchase_return_id"):
        return True

    text = f"{payment.reference or ''} {payment.description or ''}"

    if _SR_REF_RE.search(text) or _PR_REF_RE.search(text):
        return True

    upper = text.upper()
    if "SALES RETURN" in upper or "PURCHASE RETURN" in upper:
        return True

    return False


# =========================
# cheque helpers
# =========================

def _filter_cheque_payments_from_rows(rows, business_id, party_id, kind, exclude_pending=True):
    """
    Filter or mark payment rows based on cheque status.
    Returns cleaned rows with pending cheques excluded if requested.
    Also marks deposited cheque rows for template display.
    """
    if not exclude_pending:
        return rows

    pending_cheque_refs = set()
    deposited_cheque_refs = set()

    if business_id and party_id:
        party = Party.objects.get(pk=party_id)
        is_both = (party.type == Party.BOTH)

        po_ids = []
        if kind == "supplier" or is_both:
            po_ids = list(
                PurchaseOrder.objects.filter(
                    business_id=business_id,
                    supplier_id=party_id,
                    is_active=True,
                    is_deleted=False,
                ).values_list("id", flat=True)
            )
        
        so_ids = []
        if kind == "customer" or is_both:
            so_ids = list(
                SalesOrder.objects.filter(
                    business_id=business_id,
                    customer_id=party_id,
                ).exclude(status=SalesOrder.Status.CANCELLED).values_list("id", flat=True)
            )

        base_qs = (
            Payment.objects.filter(
                business_id=business_id,
                payment_method=Payment.PaymentMethod.CHEQUE,
            )
            .filter(
                Q(party_id=party_id)
                | Q(applied_purchase_orders__purchase_order_id__in=po_ids)
                | Q(applied_sales_orders__sales_order_id__in=so_ids)
            )
            .distinct()
        )

        pending_payments = base_qs.filter(
            cheque_status=Payment.ChequeStatus.PENDING
        )
        deposited_payments = base_qs.filter(
            cheque_status=Payment.ChequeStatus.DEPOSITED
        )

        for payment in pending_payments:
            pending_cheque_refs.add(f"PAY#{payment.id}")
            pending_cheque_refs.add(f"PAY-{payment.id}")
            pending_cheque_refs.add(f"Payment {payment.id}")
            pending_cheque_refs.add(f"CHQ-{payment.id}")
            pending_cheque_refs.add(f"CHQ#{payment.id}")
            if payment.reference:
                pending_cheque_refs.add(payment.reference)

        for payment in deposited_payments:
            deposited_cheque_refs.add(f"PAY#{payment.id}")
            deposited_cheque_refs.add(f"PAY-{payment.id}")
            deposited_cheque_refs.add(f"Payment {payment.id}")
            deposited_cheque_refs.add(f"CHQ-{payment.id}")
            deposited_cheque_refs.add(f"CHQ#{payment.id}")
            if payment.reference:
                deposited_cheque_refs.add(payment.reference)

    filtered_rows = []
    for row in rows:
        if isinstance(row, dict):
            ref = row.get("ref", "")
            note = row.get("note", "")
        else:
            ref = getattr(row, "ref", "")
            note = getattr(row, "note", "")

        ref_str = str(ref)
        note_str = str(note)

        is_pending_cheque = False
        is_deposited_cheque = False

        for pending_ref in pending_cheque_refs:
            if pending_ref and (pending_ref in ref_str or pending_ref in note_str):
                is_pending_cheque = True
                break

        if not is_pending_cheque:
            for dep_ref in deposited_cheque_refs:
                if dep_ref and (dep_ref in ref_str or dep_ref in note_str):
                    is_deposited_cheque = True
                    break

        if not is_pending_cheque and ("PENDING" in note_str.upper() and "CHEQUE" in note_str.upper()):
            is_pending_cheque = True

        if not is_pending_cheque:
            if isinstance(row, dict):
                row["is_deposited_cheque"] = is_deposited_cheque
                filtered_rows.append(row)
            else:
                row_dict = {
                    "date": getattr(row, "date", None),
                    "ref": ref,
                    "note": note,
                    "dr": getattr(row, "dr", None),
                    "cr": getattr(row, "cr", None),
                    "source": getattr(row, "source", ""),
                    "pk": getattr(row, "pk", None),
                    "allocations": getattr(row, "allocations", None),
                    "metadata": getattr(row, "metadata", None),
                    "product_name": getattr(row, "product_name", ""),
                    "quantity": getattr(row, "quantity", ""),
                    "unit_price": getattr(row, "unit_price", ""),
                    "is_deposited_cheque": is_deposited_cheque,
                }
                filtered_rows.append(row_dict)

    return filtered_rows


# =========================
# payment and bank movement totals
# =========================

def _compute_payment_totals_for_party(
    party_id: int,
    kind: str,
    biz_ids: list[int] | None = None,
    date_from=None,
    date_to=None,
):
    """
    Compute total Dr and Cr effect of standalone Payments for a party.

    Includes.
      Cash receipts or payments.
      Bank transfer receipts or payments.
      Cheques with cheque_status != PENDING.

    Excludes.
      Pending cheques.
      For suppliers. payments linked to PurchaseOrders.
      For customers. payments linked to SalesOrders.
      Any payment identified as a refund for Sales Return or Purchase Return.
    """
    qs = (
        Payment.objects.select_related("business", "bank_account")
        .filter(party_id=party_id)
    )

    kind = (kind or "customer").strip().lower()

    party = Party.objects.get(pk=party_id)
    is_both = (party.type == Party.BOTH)

    if kind == "supplier" or is_both:
        qs = qs.filter(applied_purchase_orders__isnull=True)
        if hasattr(Payment, "applied_purchase_returns"):
            qs = qs.filter(applied_purchase_returns__isnull=True)

    if kind == "customer" or is_both:
        if hasattr(Payment, "applied_sales_orders"):
            qs = qs.filter(applied_sales_orders__isnull=True)
        elif hasattr(Payment, "sales_orders"):
            qs = qs.filter(sales_orders__isnull=True)
        if hasattr(Payment, "applied_sales_returns"):
            qs = qs.filter(applied_sales_returns__isnull=True)

    if biz_ids:
        qs = qs.filter(business_id__in=biz_ids)
    else:
        qs = qs.filter(business__is_deleted=False, business__is_active=True)

    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    total_dr = Decimal("0.00")
    total_cr = Decimal("0.00")

    for p in qs:
        if (
            p.payment_method == Payment.PaymentMethod.CHEQUE
            and getattr(p, "cheque_status", None) == Payment.ChequeStatus.PENDING
        ):
            continue

        if _is_return_refund_payment(p):
            continue

        amount = _q2_decimal(p.amount) or Decimal("0.00")

        dr = None
        cr = None

        if getattr(p, "direction", None) == Payment.IN:
            cr = amount
        elif getattr(p, "direction", None) == Payment.OUT:
            dr = amount

        if dr:
            total_dr += dr
        if cr:
            total_cr += cr

    return total_dr, total_cr


def _compute_bankmovement_totals_for_party(
    party_id: int,
    kind: str,
    biz_ids: list[int] | None = None,
    date_from=None,
    date_to=None,
):
    """
    Extra totals from BankMovement for this party.
    Used for supplier cheque payments.
    
    FIXED: Now includes all cheque payments (with or without PO).
    """
    party = Party.objects.get(pk=party_id)
    is_both = (party.type == Party.BOTH)

    if kind.lower() != "supplier" and not is_both:
        return Decimal("0.00"), Decimal("0.00")

    qs = BankMovement.objects.select_related(
        "purchase_order",
        "purchase_order__business",
        "from_bank",
    ).filter(
        movement_type=BankMovement.CHEQUE_PAYMENT,
        party_id=party_id,
    )

    if biz_ids:
        q_with_po = Q(purchase_order__business_id__in=biz_ids)
        q_without_po = Q(purchase_order__isnull=True)
        qs = qs.filter(q_with_po | q_without_po)
    else:
        qs = qs.filter(
            Q(purchase_order__business__is_deleted=False) | Q(purchase_order__isnull=True),
            Q(purchase_order__business__is_active=True) | Q(purchase_order__isnull=True),
        )

    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    total_dr = Decimal("0.00")
    total_cr = Decimal("0.00")

    for mv in qs:
        # REMOVED: if getattr(mv, "purchase_order_id", None): continue
        # Now we include ALL cheque payments
        
        amount = _q2_decimal(mv.amount) or Decimal("0.00")
        if amount <= 0:
            continue
        total_dr += amount

    return total_dr, total_cr


def _recalculate_totals_excluding_pending(
    rows,
    opening_dr: Decimal = Decimal("0.00"),
    opening_cr: Decimal = Decimal("0.00"),
):
    total_dr = opening_dr
    total_cr = opening_cr

    for row in rows:
        if isinstance(row, dict):
            dr = row.get("dr")
            cr = row.get("cr")
        else:
            dr = getattr(row, "dr", None)
            cr = getattr(row, "cr", None)

        if dr:
            total_dr += Decimal(str(dr))
        if cr:
            total_cr += Decimal(str(cr))

    balance = total_dr - total_cr

    return {
        "total_dr": total_dr,
        "total_cr": total_cr,
        "balance_abs": abs(balance),
        "balance_side": "Dr" if balance >= 0 else "Cr",
    }


def _compute_opening_before_date_for_party(
    kind: str,
    party_id: int,
    biz_list: list[Business],
    biz_ids: list[int],
    date_from: date | None,
):
    """
    Compute opening totals (Dr, Cr) before date_from across all businesses.
    """
    if not date_from:
        return Decimal("0.00"), Decimal("0.00")

    prev_day = date_from - timedelta(days=1)

    total_dr = Decimal("0.00")
    total_cr = Decimal("0.00")

    kind_norm = (kind or "customer").strip().lower()
    opening_kept = False

    for b in biz_list:
        rows_before, _totals_before, _ = build_ledger(
            kind=kind_norm,
            business_id=b.id,
            entity_id=party_id,
            date_from=None,
            date_to=prev_day,
        )
        if not rows_before:
            continue

        filtered = _filter_cheque_payments_from_rows(
            rows_before,
            b.id,
            party_id,
            kind=kind_norm,
            exclude_pending=True,
        )
        if not filtered:
            continue

        cleaned_rows, ob_dr, ob_cr = _extract_opening(filtered)

        if not opening_kept:
            stats = _recalculate_totals_excluding_pending(
                cleaned_rows,
                ob_dr,
                ob_cr,
            )
            if ob_dr > 0 or ob_cr > 0:
                opening_kept = True
        else:
            stats = _recalculate_totals_excluding_pending(
                cleaned_rows,
                Decimal("0.00"),
                Decimal("0.00"),
            )

        total_dr += stats.get("total_dr", Decimal("0.00"))
        total_cr += stats.get("total_cr", Decimal("0.00"))

    pay_dr_before, pay_cr_before = _compute_payment_totals_for_party(
        party_id=party_id,
        kind=kind_norm,
        biz_ids=biz_ids,
        date_from=None,
        date_to=prev_day,
    )
    total_dr += pay_dr_before
    total_cr += pay_cr_before

    bm_dr_before, bm_cr_before = _compute_bankmovement_totals_for_party(
        party_id=party_id,
        kind=kind_norm,
        biz_ids=biz_ids,
        date_from=None,
        date_to=prev_day,
    )
    total_dr += bm_dr_before
    total_cr += bm_cr_before

    # Redundant fallback removed: handled by get_ob with updated global logic
    return total_dr, total_cr

# =========================
# Unified Ledger Aggregation (Helper)
# =========================
# =========================
# Unified Ledger Aggregation (Helper)
# =========================
# MOVED TO barkat.services.balance_service
from barkat.services.balance_service import get_party_balances



# =========================
# LedgersListView
# =========================

@method_decorator(login_required, name="dispatch")
class LedgersListView(View):
    template = "barkat/finance/ledgers_list.html"
    partial_template = "barkat/finance/_ledgers_table.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        kind = (request.GET.get("kind") or "customer").strip().lower()
        if kind not in ("customer", "supplier", "staff"):
            kind = "customer"

        business_param = (request.GET.get("business") or "").strip().lower()
        business = None
        if business_param.isdigit():
            business = get_object_or_404(Business, pk=int(business_param))

        q = (request.GET.get("q") or "").strip()

        # Check if supplier ledger access requires password
        # Session expires after 5 minutes (300 seconds)
        import time
        supplier_unlocked = request.session.get("supplier_ledger_unlocked", False)
        supplier_unlocked_at = request.session.get("supplier_ledger_unlocked_at", 0)
        SESSION_TIMEOUT_SECONDS = 300  # 5 minutes
        session_expired = (time.time() - supplier_unlocked_at) > SESSION_TIMEOUT_SECONDS

        # Granular: only gate if respective protection is True
        from barkat.models import UserSettings
        try:
            u_settings = UserSettings.objects.get(user=request.user)
            if kind == "supplier":
                needs_protection = u_settings.protect_payables
            elif kind == "customer":
                needs_protection = u_settings.protect_receivables
            else:
                needs_protection = False
        except UserSettings.DoesNotExist:
            needs_protection = False

        if (
            kind in ("supplier", "customer")
            and user_has_cancellation_password(request)
            and needs_protection
            and (not supplier_unlocked or session_expired)
        ):
            base = reverse("ledgers_list")
            next_url_parts = [f"kind={kind}"]
            if business_param.isdigit():
                next_url_parts.append(f"business={business_param}")
            if q:
                next_url_parts.append(urlencode({"q": q}))
            
            next_qs = "&".join(next_url_parts)
            
            # Cancel URL points to the other kind (if current is supplier, cancel to customer)
            # or just dashboard? Usually better to point to something safe.
            cancel_kind = "customer" if kind == "supplier" else "supplier"
            cancel_qs = f"kind={cancel_kind}"
            if business_param.isdigit():
                cancel_qs += f"&business={business_param}"
            
            return render(
                request,
                "barkat/finance/password_gate.html",
                {
                    "gate_title": f"{kind.title()} ledger",
                    "gate_message": f"Viewing the {kind} ledger list requires your cancellation password (User Settings).",
                    "cancel_url": f"{base}?{cancel_qs}",
                    "next_url": f"{base}?{next_qs}",
                    "action": "supplier_ledger", # Re-using same session flag for both for now
                },
            )

        if kind == "supplier":
            qs = Party.objects.filter(type__in=["VENDOR", "BOTH"])
        elif kind == "customer":
            qs = Party.objects.filter(type__in=["CUSTOMER", "BOTH"])
        else:
            qs = Staff.objects.all()

        qs = qs.filter(is_deleted=False)

        if q:
            if kind in ("supplier", "customer"):
                qs = qs.filter(
                    Q(display_name__icontains=q)
                    | Q(phone__icontains=q)
                    | Q(email__icontains=q)
                )
            else:
                qs = qs.filter(
                    Q(full_name__icontains=q)
                    | Q(phone__icontains=q)
                    | Q(cnic__icontains=q)
                )

        qs = qs.order_by("id")
        paginator = Paginator(qs, 10)
        page_obj = paginator.get_page(request.GET.get("page"))

        if kind in ("customer", "supplier"):
            # Use unified optimized aggregation
            # qs_annotated = get_party_balances(qs, business_id=business.id if business else None)

            # Map the annotation back to page_obj items
            # Since page_obj is already sliced, we need to map via ID
            # Or simpler: get_party_balances returns 'qs'. We can use it to build a dict.

            # But wait, page_obj works on 'qs'. If we modify 'qs' before paginator, it works.
            # But the code above already created 'paginator' and 'page_obj' effectively "executing" the slice (lazy).
            # If we iterate page_obj, we can fetch balances for these specific IDs efficiently.

            p_ids = [p.id for p in page_obj.object_list]
            if p_ids:
                # Use live calculation for accuracy in the list (Single Version of Truth)
                # This bypasses potential stale cached_balance values
                bals = get_party_balances(
                    Party.objects.filter(id__in=p_ids), 
                    business_id=business.id if business else None
                )
                bal_map = {b.id: (b.net_balance or Decimal("0.00")) for b in bals}

                for p in page_obj.object_list:
                    balance = bal_map.get(p.id, Decimal("0.00"))
                    p.bal_amount = abs(balance)
                    
                    # Side Logic: 
                    # Customers: Net Debit (balance > 0) is Dr.
                    # Suppliers: Net Credit (balance < 0) is Cr.
                    if balance > 0:
                        p.bal_side = "Dr"
                    elif balance < 0:
                        p.bal_side = "Cr"
                    else:
                        p.bal_side = "" # Balanced

        else:
            for s in page_obj.object_list:
                b = getattr(s, "business", None)
                if not b:
                    s.bal_amount = None
                    s.bal_side = None
                    continue
                _rows, totals, _ = build_ledger(
                    kind="staff",
                    business_id=b.id,
                    entity_id=s.id,
                    date_from=None,
                    date_to=None,
                )
                s.bal_amount = totals.get("balance_abs")
                s.bal_side = totals.get("balance_side")

        all_mode = business is None

        # Get dynamic "All Businesses" label from user settings
        user_settings = getattr(request.user, 'settings', None)
        user_business_name = ""
        if user_settings:
            if user_settings.business_name:
                user_business_name = user_settings.business_name
            elif user_settings.default_sale_business:
                user_business_name = user_settings.default_sale_business.name
        
        all_business_label = user_business_name or "Barkat Wholesale"

        ctx = {
            "kind": kind,
            "business": business,
            "all_mode": all_mode,
            "all_business_label": all_business_label,
            "businesses": Business.objects.filter(
                is_deleted=False,
                is_active=True,
            ).order_by("name", "id"),
            "page_obj": page_obj,
            "q": q,
        }

        is_htmx = request.headers.get("HX-Request") == "true"
        template_name = self.partial_template if is_htmx else self.template
        return render(request, template_name, ctx)


# =========================
# compute single party balance helper
# =========================

def _compute_party_balance(
    kind: str,
    party_id: int,
    business: Business | None,
) -> tuple[Decimal, str]:
    """
    Returns (balance_amount, balance_side) for a party using optimized service.
    """
    qs = Party.objects.filter(pk=party_id)
    # Use optimized service
    bals = get_party_balances(qs, business_id=business.id if business else None)
    
    party = bals.first()
    if party:
        net = party.net_balance or Decimal("0.00")
        side = ""
        if net > 0:
            side = "Dr"
        elif net < 0:
            side = "Cr"
        return abs(net), side
    
    return Decimal("0.00"), ""


# =========================
# LedgerDetailView
# =========================
@method_decorator(login_required, name="dispatch")
class LedgerDetailView(View):
    template = "barkat/finance/ledger_details.html"

    def get(self, request: HttpRequest, kind: str, entity_id: int) -> HttpResponse:
        kind = (kind or "").strip().lower()
        if kind not in ("customer", "supplier", "staff"):
            return redirect("/")

        date_from = _parse_date(request.GET.get("date_from"))
        date_to = _parse_date(request.GET.get("date_to"))
        print_mode = request.GET.get("print") == "1"
        business_param = (request.GET.get("business") or "").strip().lower()
        all_mode = business_param == "all"

        # Get dynamic "All Businesses" label from user settings
        user_settings = getattr(request.user, 'settings', None)
        user_business_name = ""
        if user_settings:
            if user_settings.business_name:
                user_business_name = user_settings.business_name
            elif user_settings.default_sale_business:
                user_business_name = user_settings.default_sale_business.name

        all_business_label = user_business_name or "Barkat Wholesale"

        def _ctx_common(extra: dict) -> dict:
            extra.update(
                {
                    "date_from": date_from,
                    "date_to": date_to,
                    "print_mode": print_mode,
                    "businesses": Business.objects.filter(
                        is_deleted=False,
                        is_active=True,
                    ).order_by("name", "id"),
                    "all_mode": all_mode,
                    "all_business_label": all_business_label,
                    "user_business_name": user_business_name,
                }
            )
            return extra

        # ================= STAFF LEDGER =================
        if kind == "staff":
            staff = get_object_or_404(Staff, pk=entity_id)
            business = staff.business

            url_bid = request.GET.get("business")
            if not url_bid or not url_bid.isdigit() or int(url_bid) != business.id:
                params = {"business": business.id}
                if date_from:
                    params["date_from"] = _fmt(date_from)
                if date_to:
                    params["date_to"] = _fmt(date_to)
                if print_mode:
                    params["print"] = "1"
                return redirect(f"{request.path}?{urlencode(params)}")

            rows, totals, entity = build_ledger(
                kind="staff",
                business_id=business.id,
                entity_id=entity_id,
                date_from=date_from,
                date_to=date_to,
            )

            base_rows = _rows_to_dicts(rows)
            _compute_running_balance(base_rows)

            page_obj = (
                None
                if print_mode
                else Paginator(base_rows, 25).get_page(request.GET.get("page"))
            )

            return render(
                request,
                self.template,
                _ctx_common(
                    {
                        "kind": kind,
                        "business": business,
                        "entity": entity,
                        "rows_all": base_rows if print_mode else None,
                        "page_obj": page_obj,
                        "totals": totals,
                        "show_business_switcher": False,
                        "cheque_payments": [],
                        "cheque_pending_total": Decimal("0.00"),
                        "cheque_deposited_total": Decimal("0.00"),
                    }
                ),
            )

        # ================= PARTY LEDGER (customer or supplier) =================
        # Check if supplier ledger access requires password with 5-minute timeout
        supplier_unlocked = request.session.get("supplier_ledger_unlocked", False)
        supplier_unlocked_at = request.session.get("supplier_ledger_unlocked_at", 0)
        import time
        SESSION_TIMEOUT_SECONDS = 300  # 5 minutes
        session_expired = (time.time() - supplier_unlocked_at) > SESSION_TIMEOUT_SECONDS
        
        if (
            kind == "supplier"
            and user_has_cancellation_password(request)
            and (not supplier_unlocked or session_expired)
        ):
            return redirect(reverse("ledgers_list") + "?kind=customer")

        party = get_object_or_404(Party, pk=entity_id)
        is_both = (party.type == Party.BOTH)

        other_kind = None
        if is_both:
            other_kind = "supplier" if kind == "customer" else "customer"

        # ---------- SO bundle ----------

        # ---------- PO bundle ----------

        # ---------- cheque totals for sidebar ----------
        def _fetch_party_cheques_for_businesses(biz_ids: list[int] | None):
            qs = (
                Payment.objects.filter(
                    party_id=party.id,
                    payment_method=Payment.PaymentMethod.CHEQUE,
                )
                .select_related("business", "bank_account")
            )

            if biz_ids:
                qs = qs.filter(business_id__in=biz_ids)

            if date_from:
                qs = qs.filter(date__gte=date_from)
            if date_to:
                qs = qs.filter(date__lte=date_to)

            agg = qs.aggregate(
                pending_total=Sum(
                    "amount",
                    filter=Q(cheque_status=Payment.ChequeStatus.PENDING),
                ),
                deposited_total=Sum(
                    "amount",
                    filter=Q(cheque_status=Payment.ChequeStatus.DEPOSITED),
                ),
            )
            pending_total = agg["pending_total"] or Decimal("0.00")
            deposited_total = agg["deposited_total"] or Decimal("0.00")
            return qs, pending_total, deposited_total

        # ---------- standalone payment rows ----------
        def _build_payment_rows_for_businesses(biz_ids: list[int] | None):
            qs = (
                Payment.objects.select_related("business", "bank_account")
                .prefetch_related(
                    "applied_sales_orders",
                    "applied_sales_orders__sales_order",
                    "applied_purchase_orders",
                    "applied_purchase_orders__purchase_order"
                )
                .filter(party_id=party.id)
            )

            # Unified: Exclude payments applied to orders or returns, regardless of ledger kind.
            # These are already shown via customer_rows/supplier_rows in ledger.py.
            qs = qs.filter(applied_purchase_orders__isnull=True)
            if hasattr(Payment, "applied_sales_orders"):
                qs = qs.filter(applied_sales_orders__isnull=True)
            elif hasattr(Payment, "sales_orders"):
                qs = qs.filter(sales_orders__isnull=True)
                
            # Exclude refund payments
            if hasattr(Payment, "applied_sales_returns"):
                qs = qs.filter(applied_sales_returns__isnull=True)
            if hasattr(Payment, "applied_purchase_returns"):
                qs = qs.filter(applied_purchase_returns__isnull=True)

            if biz_ids:
                qs = qs.filter(business_id__in=biz_ids)
            else:
                qs = qs.filter(business__is_deleted=False, business__is_active=True)

            if date_from:
                qs = qs.filter(date__gte=date_from)
            if date_to:
                qs = qs.filter(date__lte=date_to)

            rows = []
            total_dr = Decimal("0.00")
            total_cr = Decimal("0.00")

            for p in qs:
                if (
                    p.payment_method == Payment.PaymentMethod.CHEQUE
                    and getattr(p, "cheque_status", None) == Payment.ChequeStatus.PENDING
                ):
                    continue

                if _is_return_refund_payment(p):
                    continue

                amount = _q2_decimal(p.amount) or Decimal("0.00")

                ref = p.reference or f"PAY-{p.pk}"
                method_label = p.get_payment_method_display()
                bank_name = ""
                if p.bank_account_id:
                    bank_name = f" ({p.bank_account.name})"

                note = p.description or f"{method_label}{bank_name}"

                # Build Allocations
                allocations = []
                for app in p.applied_sales_orders.all():
                    allocations.append({
                        "target": f"SO #{app.sales_order_id}",
                        "amount": app.amount
                    })
                for app in p.applied_purchase_orders.all():
                    allocations.append({
                        "target": f"PO #{app.purchase_order_id}",
                        "amount": app.amount
                    })

                dr = None
                cr = None

                if kind == "customer":
                    if p.direction == Payment.IN:
                        cr = amount
                    else:
                        dr = amount
                elif kind == "supplier":
                    if p.direction == Payment.OUT:
                        dr = amount
                    else:
                        cr = amount

                if dr is None and cr is None:
                    continue

                rows.append(
                    {
                        "date": p.date,
                        "ref": ref,
                        "note": note,
                        "dr": dr,
                        "cr": cr,
                        "biz_id": p.business_id,
                        "biz_name": getattr(p.business, "name", "") if p.business_id else "",
                        "is_payment_row": True,
                        "allocations": allocations,
                        "payment_method": method_label,
                        "bank_name": bank_name,
                    }
                )

                if dr:
                    total_dr += dr
                if cr:
                    total_cr += cr

            return rows, total_dr, total_cr

        # ---------- BankMovement rows for cheque payments ----------
        def _build_bankmovement_rows_for_businesses(biz_ids: list[int] | None):
            """
            Extra rows from BankMovement for this party.
            Used for supplier cheque payments.
            
            FIXED: Now properly includes cheque payments both with and without PO links.
            """
            # Unified: Show bank movements for any party type.
            # if kind != "supplier" and not is_both:
            #     return [], Decimal("0.00"), Decimal("0.00")

            qs = BankMovement.objects.select_related(
                "purchase_order",
                "purchase_order__business",
                "from_bank",
                "party",
            ).filter(
                movement_type=BankMovement.CHEQUE_PAYMENT,
                party_id=party.id,
            )

            if biz_ids:
                # For cheques linked to PO, filter by PO business
                # For cheques without PO, include them too
                q_with_po = Q(purchase_order__business_id__in=biz_ids)
                q_without_po = Q(purchase_order__isnull=True)
                qs = qs.filter(q_with_po | q_without_po)

            if date_from:
                qs = qs.filter(date__gte=date_from)
            if date_to:
                qs = qs.filter(date__lte=date_to)

            rows = []
            total_dr = Decimal("0.00")
            total_cr = Decimal("0.00")

            for mv in qs:
                # REMOVED THE SKIP LOGIC - now we include ALL cheque payments
                
                amount = _q2_decimal(mv.amount) or Decimal("0.00")
                if amount <= 0:
                    continue

                # Build reference
                ref_parts = []
                if mv.reference_no:
                    ref_parts.append(mv.reference_no)
                else:
                    ref_parts.append(f"CHQ-{mv.id}")
                
                # Add PO reference if linked
                if mv.purchase_order_id:
                    ref_parts.append(f"PO#{mv.purchase_order_id}")
                
                ref = " | ".join(ref_parts)

                # Build note
                note_bits = []
                if mv.from_bank:
                    note_bits.append(f"Cheque from {mv.from_bank.name}")
                
                if mv.purchase_order_id:
                    po_ref = f"for PO #{mv.purchase_order_id}"
                    note_bits.append(po_ref)
                
                if mv.notes:
                    note_bits.append(mv.notes)
                
                if mv.party:
                    note_bits.append(f"to {mv.party.display_name}")

                note = " — ".join(note_bits) if note_bits else "Cheque payment"

                # For supplier ledger, cheque payment is always a debit (payment to supplier)
                dr = amount
                cr = None

                # Determine business for display
                biz_id = None
                biz_name = ""
                if mv.purchase_order and mv.purchase_order.business:
                    biz_id = mv.purchase_order.business_id
                    biz_name = mv.purchase_order.business.name

                rows.append(
                    {
                        "date": mv.date,
                        "ref": ref,
                        "note": note,
                        "dr": dr,
                        "cr": cr,
                        "biz_id": biz_id,
                        "biz_name": biz_name,
                        "is_bankmovement_row": True,
                        "is_cheque": True,
                        "movement_id": mv.id,
                    }
                )

                total_dr += dr

            return rows, total_dr, total_cr

        # ================= ALL BUSINESSES =================
        if all_mode:
            biz_list = list(
                Business.objects.filter(
                    is_deleted=False,
                    is_active=True,
                ).order_by("name", "id")
            )
            biz_ids = [b.id for b in biz_list]

            cheque_qs, pending_total, deposited_total = _fetch_party_cheques_for_businesses(
                biz_ids
            )

            all_rows = []
            total_dr = Decimal("0.00")
            total_cr = Decimal("0.00")

            open_dr = Decimal("0.00")
            open_cr = Decimal("0.00")

            if date_from:
                open_dr, open_cr = _compute_opening_before_date_for_party(
                    kind=kind,
                    party_id=party.id,
                    biz_list=biz_list,
                    biz_ids=biz_ids,
                    date_from=date_from,
                )

            opening_kept = False

            for b in biz_list:
                rows_b, _totals_b, _ = build_ledger(
                    kind=kind,
                    business_id=b.id,
                    entity_id=entity_id,
                    date_from=date_from,
                    date_to=date_to,
                )

                if not rows_b:
                    continue

                filtered_b = _filter_cheque_payments_from_rows(
                    rows_b,
                    b.id,
                    entity_id,
                    kind=kind,
                    exclude_pending=True,
                )

                if not filtered_b:
                    continue

                cleaned_rows, ob_dr, ob_cr = _extract_opening(filtered_b)

                if not date_from and not opening_kept and (ob_dr > 0 or ob_cr > 0):
                    open_dr += ob_dr
                    open_cr += ob_cr
                    opening_kept = True

                stats = _recalculate_totals_excluding_pending(cleaned_rows)

                dict_rows = _rows_to_dicts(
                    cleaned_rows,
                    {"biz_id": b.id, "biz_name": b.name},
                )


                all_rows.extend(dict_rows)
                total_dr += stats.get("total_dr", Decimal("0.00"))
                total_cr += stats.get("total_cr", Decimal("0.00"))

            payment_rows, pay_dr_total, pay_cr_total = _build_payment_rows_for_businesses(
                biz_ids
            )
            all_rows.extend(payment_rows)
            total_dr += pay_dr_total
            total_cr += pay_cr_total

            # FIXED: Now includes all BankMovement cheque payments
            bm_rows, bm_dr_total, bm_cr_total = _build_bankmovement_rows_for_businesses(
                biz_ids
            )
            all_rows.extend(bm_rows)
            total_dr += bm_dr_total
            total_cr += bm_cr_total

            # Fallback for opening balance if not captured in business loop (e.g. party has no default_business)
            if not date_from and not opening_kept:
                from barkat.ledger import opening_balance as get_ob
                ob, side = get_ob(kind, party)
                if ob > 0:
                    if side == 'Dr':
                        open_dr += ob
                    else:
                        open_cr += ob
                    opening_kept = True

            total_dr += open_dr
            total_cr += open_cr

            if open_dr != open_cr:
                opening_balance = open_dr - open_cr
                bf_dr = opening_balance if opening_balance > 0 else None
                bf_cr = -opening_balance if opening_balance < 0 else None
                bf_row = {
                    "date": date_from or None,
                    "ref": "B/F",
                    "note": "Balance brought forward",
                    "dr": bf_dr,
                    "cr": bf_cr,
                    "biz_id": None,
                    "biz_name": "",
                    "is_opening_row": True,
                }
                all_rows.insert(0, bf_row)

            all_rows.sort(
                key=lambda x: (
                    (x.get("date") or date.min),
                    str(x.get("ref") or ""),
                ),
            )
            # Ensure Opening Balance row is at the absolute top if dates are equal
            all_rows.sort(key=lambda x: 0 if x.get("is_opening_row") else 1)
            all_rows.sort(key=lambda x: (x.get("date") or date.min))

            _compute_running_balance(all_rows)

            total_dr = _q2_decimal(total_dr) or Decimal("0.00")
            total_cr = _q2_decimal(total_cr) or Decimal("0.00")
            balance = total_dr - total_cr

            totals = {
                "total_dr": total_dr,
                "total_cr": total_cr,
                "balance_abs": _q2_decimal(abs(balance)) or Decimal("0.00"),
                "balance_side": "Dr" if balance >= 0 else "Cr",
            }

            page_obj = (
                None
                if print_mode
                else Paginator(all_rows, 25).get_page(request.GET.get("page"))
            )

            return render(
                request,
                self.template,
                _ctx_common(
                    {
                        "kind": kind,
                        "business": None,
                        "entity": party,
                        "rows_all": all_rows if print_mode else None,
                        "page_obj": page_obj,
                        "totals": totals,
                        "show_business_switcher": True,
                        "other_kind": other_kind,
                        "is_both": is_both,
                        "cheque_payments": cheque_qs,
                        "cheque_pending_total": pending_total,
                        "cheque_deposited_total": deposited_total,
                    }
                ),
            )

        # ================= SINGLE BUSINESS =================
        business_id = request.GET.get("business")
        if not business_id or not business_id.isdigit():
            inferred = getattr(party, "default_business", None)
            target_biz = inferred or Business.objects.order_by("name", "id").first()
            if not target_biz:
                return HttpResponse(
                    "No Business found. Please create a Business first.",
                    status=400,
                )
            params = {"business": target_biz.id}
            if date_from:
                params["date_from"] = _fmt(date_from)
            if date_to:
                params["date_to"] = _fmt(date_to)
            if print_mode:
                params["print"] = "1"
            return redirect(f"{request.path}?{urlencode(params)}")

        business = get_object_or_404(Business, pk=int(business_id))

        rows, _totals_base, _entity = build_ledger(
            kind=kind,
            business_id=business.id,
            entity_id=entity_id,
            date_from=date_from,
            date_to=date_to,
        )

        filtered_rows = _filter_cheque_payments_from_rows(
            rows,
            business.id,
            entity_id,
            kind=kind,
            exclude_pending=True,
        )

        cleaned_rows, _ob_dr, _ob_cr = _extract_opening(filtered_rows)

        range_stats = _recalculate_totals_excluding_pending(cleaned_rows)

        base_rows = _rows_to_dicts(cleaned_rows)



        payment_rows, pay_dr_total, pay_cr_total = _build_payment_rows_for_businesses(
            [business.id]
        )
        base_rows.extend(payment_rows)

        # FIXED: Now includes all BankMovement cheque payments
        bm_rows, bm_dr_total, bm_cr_total = _build_bankmovement_rows_for_businesses(
            [business.id]
        )
        base_rows.extend(bm_rows)

        open_dr = Decimal("0.00")
        open_cr = Decimal("0.00")
        if date_from:
            open_dr, open_cr = _compute_opening_before_date_for_party(
                kind=kind,
                party_id=party.id,
                biz_list=[business],
                biz_ids=[business.id],
                date_from=date_from,
            )

        total_dr = (
            open_dr
            + range_stats.get("total_dr", Decimal("0.00"))
            + pay_dr_total
            + bm_dr_total
        )
        total_cr = (
            open_cr
            + range_stats.get("total_cr", Decimal("0.00"))
            + pay_cr_total
            + bm_cr_total
        )

        if date_from and open_dr != open_cr:
            opening_balance = open_dr - open_cr
            bf_dr = opening_balance if opening_balance > 0 else None
            bf_cr = -opening_balance if opening_balance < 0 else None
            bf_row = {
                "date": date_from,
                "ref": "B/F",
                "note": "Balance brought forward",
                "dr": bf_dr,
                "cr": bf_cr,
                "biz_id": business.id,
                "biz_name": business.name,
                "is_opening_row": True,
            }
            base_rows.insert(0, bf_row)

        # Unified Sorting: Date ASC, Opening row first
        base_rows.sort(
            key=lambda x: (
                (x.get("date") or date.min),
                0 if x.get("is_opening_row") else 1,
                str(x.get("ref") or ""),
            )
        )

        _compute_running_balance(base_rows)
        
        # If the user ever wants DESC UI, we would reverse here. 
        # But for now we keep it ASC (Traditional) as requested for print.
        # Since UI is already ASC, we don't need to do anything extra.

        total_dr = _q2_decimal(total_dr) or Decimal("0.00")
        total_cr = _q2_decimal(total_cr) or Decimal("0.00")
        balance = total_dr - total_cr

        totals = {
            "total_dr": total_dr,
            "total_cr": total_cr,
            "balance_abs": _q2_decimal(abs(balance)) or Decimal("0.00"),
            "balance_side": "Dr" if balance >= 0 else "Cr",
        }

        page_obj = (
            None
            if print_mode
            else Paginator(base_rows, 25).get_page(request.GET.get("page"))
        )

        cheque_qs, pending_total, deposited_total = _fetch_party_cheques_for_businesses(
            [business.id]
        )

        return render(
            request,
            self.template,
            _ctx_common(
                {
                    "kind": kind,
                    "business": business,
                    "entity": party,
                    "rows_all": base_rows if print_mode else None,
                    "page_obj": page_obj,
                    "totals": totals,
                    "show_business_switcher": True,
                    "other_kind": other_kind,
                    "is_both": is_both,
                    "cheque_payments": cheque_qs,
                    "cheque_pending_total": pending_total,
                    "cheque_deposited_total": deposited_total,
                }
            ),
        )


@login_required
@require_GET
def party_balance_api(request):
    """
    Unified balance endpoint. Returns {ok, amount, side, net_balance, meaning}.
    Helper for real-time form updates.
    """
    party_id = request.GET.get('party_id')
    try:
        if not party_id:
            return JsonResponse({'ok': False, 'error': 'No party_id provided'})

        # If business_id is passed, we filter by that business.
        # Otherwise, we sum for ALL businesses (Unified Global Balance).
        business_id = request.GET.get('business_id')
        if business_id:
            try:
                business_id = int(business_id)
            except ValueError:
                business_id = None
        
        # Parse Exclusions if provided (for Edit Mode)
        exclude_id = request.GET.get('exclude_id')
        exclude_type = request.GET.get('exclude_type')
        
        exclude_so_ids = []
        exclude_po_ids = []
        
        if exclude_id and exclude_type:
            try:
                ex_id = int(exclude_id)
                if exclude_type == 'sales_order':
                    exclude_so_ids.append(ex_id)
                elif exclude_type == 'purchase_order':
                    exclude_po_ids.append(ex_id)
            except ValueError:
                pass

        qs = Party.objects.filter(pk=party_id)
        qs = get_party_balances(
            qs, 
            business_id=business_id,
            exclude_so_ids=exclude_so_ids,
            exclude_po_ids=exclude_po_ids
        )
        
        party = qs.first()
        if not party:
            return JsonResponse({'ok': False, 'error': 'Party not found'})

        net = party.net_balance or Decimal("0.00")
        
        # side logic: Dr vs Cr
        side = "Dr"
        if net < 0:
            side = "Cr"
        
        amount = abs(net)
        
        # simple meaningful text
        meaning = "Balance"
        if net > 0:
            meaning = "Receivable (They owe you)"
        elif net < 0:
            meaning = "Payable (You owe them)"
        
        return JsonResponse({
            "ok": True,
            "amount": f"{amount:.2f}",
            "side": side,
            "net_balance": f"{net:.2f}",
            "meaning": meaning
        })

    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)})


# Legacy wrappers for backward compatibility if needed, 
# or redirect them to the new logic if they are distinct in purpose.
# But for now, let's keep them if frontend uses them, but redirect logic.

@login_required
@require_GET
def supplier_balance_api(request):
    # Map to new logic
    request.GET = request.GET.copy()
    if 'supplier_id' in request.GET:
        request.GET['party_id'] = request.GET['supplier_id']
    return party_balance_api(request)

@login_required
@require_GET
def customer_balance_api(request):
    # Map to new logic
    request.GET = request.GET.copy()
    if 'customer_id' in request.GET:
        request.GET['party_id'] = request.GET['customer_id']
    return party_balance_api(request)

class PartySummaryView(View):
    """
    Summary of customers or suppliers over all businesses.
    Shows only Remaining Amount (ledger balance) per party.
    - Positive (Dr). party owes us
    - Negative (Cr). we owe party
    Zero balances are skipped.
    """
    template_name = "barkat/finance/party_summary.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        kind = (request.GET.get("kind") or "customer").strip().lower()
        if kind not in ("customer", "supplier"):
            kind = "customer"

        q = (request.GET.get("q") or "").strip()
        date_from = _parse_date(request.GET.get("date_from"))
        date_to = _parse_date(request.GET.get("date_to"))

        if date_from and date_to and date_from > date_to:
            date_from, date_to = date_to, date_from

        # base party queryset. across all businesses
        if kind == "customer":
            party_qs = Party.objects.filter(type__in=[Party.CUSTOMER, Party.BOTH])
        else:
            party_qs = Party.objects.filter(type__in=[Party.VENDOR, Party.BOTH])

        party_qs = party_qs.filter(is_deleted=False)

        if q:
            party_qs = party_qs.filter(
                Q(display_name__icontains=q)
                | Q(phone__icontains=q)
                | Q(email__icontains=q)
            )

        party_qs = party_qs.order_by("display_name", "id")

        # Use optimized service for ALL filter parties at once
        # Global balance aggregated over all active businesses
        bals = get_party_balances(party_qs) 
        
        rows = []
        for p in bals:
            balance = p.net_balance or Decimal("0.00")
            if balance == 0:
                continue

            rows.append({
                "party": p,
                "balance_abs": abs(balance),
                "balance_side": "Dr" if balance >= 0 else "Cr",
            })

        # sort by largest remaining balance
        rows.sort(key=lambda r: r["balance_abs"], reverse=True)

        ctx = {
            "kind": kind,
            "rows": rows,
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
        }
        return render(request, self.template_name, ctx)

@method_decorator(login_required, name='dispatch')
class BusinessesView(ListView):
    template_name = "barkat/dashboard/businesses.html"
    context_object_name = "businesses"
    paginate_by = 25  # optional

    def get_queryset(self):
        return Business.objects.filter(is_active=True, is_deleted=False).select_related('summary').order_by("-id")

    # ---- helper to build overall party summary (all businesses) ----
    def _build_party_summary(self, kind: str, q: str | None,
                             date_from, date_to):
        """
        Returns list of dicts:
          {
            "party": Party instance,
            "balance_abs": Decimal,
            "balance_side": "Dr" or "Cr",
          }
        Only nonzero balances. merged across all active businesses.
        Now includes standalone Payment rows and BankMovement cheque payments.
        """
        kind = (kind or "customer").strip().lower()
        if kind not in ("customer", "supplier"):
            kind = "customer"

        # base party queryset
        if kind == "customer":
            party_qs = Party.objects.filter(
                type__in=[Party.CUSTOMER, Party.BOTH]
            )
        else:
            party_qs = Party.objects.filter(
                type__in=[Party.VENDOR, Party.BOTH]
            )

        party_qs = party_qs.filter(is_deleted=False)

        if q:
            party_qs = party_qs.filter(
                Q(display_name__icontains=q)
                | Q(phone__icontains=q)
                | Q(email__icontains=q)
            )

        party_qs = party_qs.order_by("display_name", "id")

        # Use optimized service
        bals = get_party_balances(party_qs)
        
        rows = []
        for p in bals:
            balance = p.net_balance or Decimal("0.00")
            if balance == 0:
                continue

            rows.append({
                "party": p,
                "balance_abs": abs(balance),
                "balance_side": "Dr" if balance >= 0 else "Cr",
            })
        
        # sort by largest remaining
        rows.sort(key=lambda r: r["balance_abs"], reverse=True)
        return rows

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # party summary filters from querystring
        request = self.request
        party_kind = (request.GET.get("kind") or "customer").strip().lower()
        if party_kind not in ("customer", "supplier"):
            party_kind = "customer"

        party_q = (request.GET.get("q") or "").strip()
        date_from = _parse_date(request.GET.get("date_from"))
        date_to = _parse_date(request.GET.get("date_to"))

        if date_from and date_to and date_from > date_to:
            date_from, date_to = date_to, date_from

        party_rows = self._build_party_summary(
            kind=party_kind,
            q=party_q,
            date_from=date_from,
            date_to=date_to,
        )

        # 1. Unified Financial Metrics (Global and Per-Business)
        from barkat.services.financial_logic import get_business_financials
        
        # Global Totals
        global_stats = get_business_financials()
        ctx["total_receivables"] = global_stats["total_receivables"]
        ctx["total_payables"] = global_stats["total_payables"]
        ctx["cash_in_hand"] = global_stats["cash_in_hand"]
        ctx["total_inventory_valuation"] = global_stats["inventory_value"]
        ctx["global_net_worth"] = global_stats["net_worth"]

        # Enrich per-business stats for the table (Live data)
        # Note: 'businesses' is the paged queryset from ListView
        businesses = ctx.get('businesses', [])
        for b in businesses:
            b.live_summary = get_business_financials(b.id)

        today = timezone.now().date()
        ctx["today_date"] = today
        
        ctx["csrf_token"] = get_token(self.request)
        ctx["party_kind"] = party_kind
        ctx["party_rows"] = party_rows
        ctx["party_q"] = party_q
        ctx["party_date_from"] = date_from
        ctx["party_date_to"] = date_to
        return ctx

def _get_last_payment_for_party(
    party_id: int,
    kind: str,
    date_from=None,
    date_to=None,
):
    """
    Return the last relevant Payment for this party and kind.
    For customers. last time they paid us (direction=IN).
    For suppliers. last time we paid them (direction=OUT).
    Excludes pending cheques and return refund payments.
    """
    qs = Payment.objects.filter(party_id=party_id)

    kind = (kind or "customer").strip().lower()

    if hasattr(Payment, "direction"):
        if kind == "customer":
            qs = qs.filter(direction=Payment.IN)
        elif kind == "supplier":
            qs = qs.filter(direction=Payment.OUT)

    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    qs = qs.select_related("business", "bank_account")

    qs = qs.exclude(
        payment_method=Payment.PaymentMethod.CHEQUE,
        cheque_status=Payment.ChequeStatus.PENDING,
    )

    qs = [p for p in qs if not _is_return_refund_payment(p)]

    if not qs:
        return None

    qs.sort(key=lambda p: (p.date or timezone.now().date(), p.id), reverse=True)
    return qs[0]

@method_decorator(login_required, name="dispatch")
class PartyBalancesView(View):
    template = "barkat/finance/party_balances.html"

    def _compute_totals_upto(self, *, kind: str, party_id: int, biz_list, biz_ids, date_to) -> tuple[Decimal, Decimal]:
        if date_to is None:
            target = date.today() + timedelta(days=3650)
        else:
            target = date_to
        date_from_for_helper = target + timedelta(days=1)
        
        # This helper function must exist in your ledger_views.py or utils
        return _compute_opening_before_date_for_party(
            kind=kind, party_id=party_id, biz_list=biz_list, biz_ids=biz_ids, date_from=date_from_for_helper,
        )

    def get(self, request: HttpRequest) -> HttpResponse:
        q = (request.GET.get("q") or "").strip()
        date_from = _parse_date(request.GET.get("date_from"))
        date_to = _parse_date(request.GET.get("date_to"))
        
        # --- BUSINESS FILTERING LOGIC ---
        selected_biz_id = request.GET.get("business")
        all_businesses = list(
            Business.objects.filter(is_deleted=False, is_active=True).order_by("name", "id")
        )

        if selected_biz_id and selected_biz_id.isdigit():
            active_biz = Business.objects.filter(id=selected_biz_id, is_deleted=False).first()
            biz_list = [active_biz] if active_biz else all_businesses
            biz_ids = [active_biz.id] if active_biz else [b.id for b in all_businesses]
        else:
            biz_list = all_businesses
            biz_ids = [b.id for b in all_businesses]

        # --- DYNAMIC PARTY FILTERING (BASED ON YOUR MODELS) ---
        # We find parties that have activity in the selected business(es) 
        # by checking Sales, Purchases, and Payments.
        
        relevant_cust_ids = set()
        relevant_supp_ids = set()

        # Check Sales Orders
        relevant_cust_ids.update(
            SalesOrder.objects.filter(business_id__in=biz_ids).values_list('customer_id', flat=True)
        )
        # Check Purchase Orders
        relevant_supp_ids.update(
            PurchaseOrder.objects.filter(business_id__in=biz_ids).values_list('supplier_id', flat=True)
        )
        # Check General Payments
        payment_parties = Payment.objects.filter(business_id__in=biz_ids).values_list('party_id', flat=True)
        # We don't know if payment is cust/supp here, so we add to both sets to be safe 
        # (the .filter(type=...) later will clean this up)
        relevant_cust_ids.update(payment_parties)
        relevant_supp_ids.update(payment_parties)

        cust_qs = Party.objects.filter(
            id__in=relevant_cust_ids, 
            type__in=[Party.CUSTOMER, Party.BOTH], 
            is_deleted=False
        )
        supp_qs = Party.objects.filter(
            id__in=relevant_supp_ids, 
            type__in=[Party.VENDOR, Party.BOTH], 
            is_deleted=False
        )

        if q:
            filter_q = Q(display_name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q)
            cust_qs = cust_qs.filter(filter_q)
            supp_qs = supp_qs.filter(filter_q)

        cust_qs = cust_qs.order_by("display_name", "id")
        supp_qs = supp_qs.order_by("display_name", "id")

        def build_rows(kind: str, party_qs):
            rows = []
            total_opening_bal = Decimal("0.00")
            total_period_dr = Decimal("0.00")
            total_period_cr = Decimal("0.00")
            total_closing_bal = Decimal("0.00")

            # FETCH ALL BALANCES AT ONCE (Optimization)
            # 1. Opening Balances
            prev_to = (date_from - timedelta(days=1)) if date_from else None
            # Business scoping
            biz_id_for_service = biz_ids[0] if len(biz_ids) == 1 else None
            
            opening_bals = {}
            if prev_to:
                qs_ob = get_party_balances(party_qs, business_id=biz_id_for_service, date_to=prev_to)
                for p in qs_ob:
                    opening_bals[p.id] = {
                        'net': p.net_balance or Decimal("0.00"),
                        'dr': p.final_dr or Decimal("0.00"),
                        'cr': p.final_cr or Decimal("0.00")
                    }
            
            # 2. Closing Balances
            closing_bals = get_party_balances(party_qs, business_id=biz_id_for_service, date_to=date_to)
            
            for p in closing_bals:
                ob_data = opening_bals.get(p.id, {'net': Decimal("0.00"), 'dr': Decimal("0.00"), 'cr': Decimal("0.00")})
                
                opening_balance = ob_data['net']
                closing_balance = p.net_balance or Decimal("0.00")

                # Movements during period
                delta_dr = (p.final_dr or Decimal("0.00")) - ob_data['dr']
                delta_cr = (p.final_cr or Decimal("0.00")) - ob_data['cr']

                # Hide if totally zero and no movement
                if closing_balance == 0 and delta_dr == 0 and delta_cr == 0 and opening_balance == 0:
                    continue

                # Last Payment specifically for these businesses
                last_pay = Payment.objects.filter(
                    party_id=p.id, business_id__in=biz_ids, is_deleted=False
                ).order_by('-date').first()

                total_opening_bal += opening_balance
                total_period_dr += delta_dr
                total_period_cr += delta_cr
                total_closing_bal += closing_balance

                rows.append({
                    "party": p,
                    "opening_abs": abs(opening_balance),
                    "opening_side": "Dr" if opening_balance > 0 else "Cr" if opening_balance < 0 else "",
                    "period_debit": delta_dr,
                    "period_credit": delta_cr,
                    "balance_abs": abs(closing_balance),
                    "balance_side": "Dr" if closing_balance >= 0 else "Cr",
                    "last_paid_date": last_pay.date if last_pay else None,
                })

            rows.sort(key=lambda r: r["balance_abs"], reverse=True)
            
            grand_totals = {
                "opening_abs": abs(total_opening_bal),
                "opening_side": "Dr" if total_opening_bal > 0 else "Cr" if total_opening_bal < 0 else "",
                "period_debit": total_period_dr,
                "period_credit": total_period_cr,
                "balance_abs": abs(total_closing_bal),
                "balance_side": "Dr" if total_closing_bal >= 0 else "Cr",
            }
            return {"rows": rows, "totals": grand_totals}

        cust_results = build_rows("customer", cust_qs)
        
        from barkat.models import UserSettings
        try:
            u_settings = UserSettings.objects.get(user=request.user)
            needs_protection = u_settings.protect_payables
        except UserSettings.DoesNotExist:
            needs_protection = False

        import time
        unlocked = request.session.get("party_balances_supplier_unlocked", False)
        unlocked_at = request.session.get("party_balances_supplier_unlocked_at", 0)
        # 5 minute timeout
        session_expired = (time.time() - unlocked_at) > 300

        has_pw = user_has_cancellation_password(request)
        suppliers_unlocked = (
            not (has_pw and needs_protection) or (unlocked and not session_expired)
        )
        if suppliers_unlocked:
            supp_results = build_rows("supplier", supp_qs)
            supplier_rows = supp_results["rows"]
            supplier_totals = supp_results["totals"]
        else:
            supplier_rows = []
            supplier_totals = {
                "opening_abs": Decimal("0.00"),
                "opening_side": "",
                "period_debit": Decimal("0.00"),
                "period_credit": Decimal("0.00"),
                "balance_abs": Decimal("0.00"),
                "balance_side": "",
            }

        reload_qs = request.GET.urlencode()
        party_balances_reload_url = request.path + ("?" + reload_qs if reload_qs else "")

        ctx = {
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
            "businesses": all_businesses,
            "selected_biz_id": selected_biz_id,
            "customer_rows": cust_results["rows"],
            "customer_totals": cust_results["totals"],
            "supplier_rows": supplier_rows,
            "supplier_totals": supplier_totals,
            "suppliers_unlocked": suppliers_unlocked,
            "show_password_modal": has_pw and not suppliers_unlocked,
            "party_balances_reload_url": party_balances_reload_url,
        }
        return render(request, self.template, ctx)
