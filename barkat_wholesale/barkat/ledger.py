# barkat/ledger.py
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Literal, Optional, Tuple
from datetime import date, datetime
from calendar import monthrange

from django.db.models import Sum, Q
from django.utils import timezone
from django.db.models.functions import TruncDate

from .models import (
    Party, Staff, Expense, ExpenseCategory,
    SalesInvoice, SalesInvoiceReceipt, SalesReturn, SalesReturnRefund,
    SalesOrder, SalesOrderReceipt,
    PurchaseOrder, PurchaseOrderPayment, PurchaseReturn, PurchaseReturnRefund,
)

LedgerKind = Literal["customer", "supplier", "staff"]

@dataclass
class LedgerRow:
    date: date
    ref: str
    note: str
    dr: Decimal
    cr: Decimal
    source: str   # model tag
    pk: int | None = None
    allocations: list | None = None
    metadata: dict | None = None
    # Itemized fields
    product_name: str = ""
    quantity: str = ""
    unit_price: str = ""

def _q(v: Decimal | None) -> Decimal:
    return (v or Decimal("0.00")).quantize(Decimal("0.01"))

def _as_date(dt) -> date:
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt
    if isinstance(dt, datetime):
        return timezone.localtime(dt).date() if timezone.is_aware(dt) else dt.date()
    return date.today()

# ----- date helpers -----------------------------------------------------------
def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)

def _month_end(d: date) -> date:
    return date(d.year, d.month, monthrange(d.year, d.month)[1])

def _iter_month_starts(start: date, end: date):
    """Yield 1st of each month from start..end inclusive."""
    y, m = start.year, start.month
    cur = date(y, m, 1)
    while cur <= end:
        yield cur
        if m == 12:
            y += 1; m = 1
        else:
            m += 1
        cur = date(y, m, 1)

# ---------- CUSTOMER LEDGER ----------
def customer_rows(
    business_id: int,
    party_id: int | None,
    date_from: Optional[date],
    date_to: Optional[date],
) -> Iterable[LedgerRow]:
    # 1. Sales Invoices (Dr)
    inv_qs = (SalesInvoice.objects
              .filter(business_id=business_id, customer_id=party_id)
              .prefetch_related('items', 'items__product'))
    if date_from:
        inv_qs = inv_qs.filter(created_at__date__gte=date_from)
    if date_to:
        inv_qs = inv_qs.filter(created_at__date__lte=date_to)
    
    for inv in inv_qs:
        date_obj = _as_date(inv.created_at)
        ref = f"INV {inv.invoice_no}"
        
        # Line Items
        for it in inv.items.all():
            yield LedgerRow(
                date=date_obj, ref=ref, note="Sales Item",
                dr=_q(it.line_total()), cr=_q(0),
                source="SalesInvoiceItem", pk=it.id,
                product_name=it.product.name,
                quantity=f"{it.quantity:.2f}",
                unit_price=f"{it.unit_price:.2f}"
            )
        
        # Tax/Discount as adjustments
        if inv.tax_percent:
            tax_amt = _q(inv.total_amount * (inv.tax_percent / 100))
            yield LedgerRow(date=date_obj, ref=ref, note=f"Tax ({inv.tax_percent}%)", dr=tax_amt, cr=_q(0), source="SalesInvoiceTax", pk=inv.id)
        if inv.discount_percent:
            disc_amt = _q(inv.total_amount * (inv.discount_percent / 100))
            yield LedgerRow(date=date_obj, ref=ref, note=f"Discount ({inv.discount_percent}%)", dr=_q(0), cr=disc_amt, source="SalesInvoiceDiscount", pk=inv.id)

    # 2. Sales Orders (Retail) as Dr
    so_qs = (SalesOrder.objects
             .filter(business_id=business_id, customer_id=party_id)
             .exclude(status=SalesOrder.Status.CANCELLED)
             .prefetch_related('items', 'items__product', 'items__uom'))
    if date_from:
        so_qs = so_qs.filter(created_at__date__gte=date_from)
    if date_to:
        so_qs = so_qs.filter(created_at__date__lte=date_to)
    
    for so in so_qs:
        date_obj = _as_date(so.created_at)
        ref = f"SO #{so.id}"
        
        for it in so.items.all():
            uom_code = it.uom.code if it.uom else ""
            yield LedgerRow(
                date=date_obj, ref=ref, note="Order Item",
                dr=_q(it.line_total()), cr=_q(0),
                source="SalesOrderItem", pk=it.id,
                product_name=it.product.name,
                quantity=f"{it.quantity:.2f} {uom_code}".strip(),
                unit_price=f"{it.unit_price:.2f}"
            )
            
        if so.tax_percent:
            tax_amt = _q(so.total_amount * (so.tax_percent / 100))
            yield LedgerRow(date=date_obj, ref=ref, note=f"Tax ({so.tax_percent}%)", dr=tax_amt, cr=_q(0), source="SalesOrderTax", pk=so.id)
        if so.discount_percent:
            disc_amt = _q(so.total_amount * (so.discount_percent / 100))
            yield LedgerRow(date=date_obj, ref=ref, note=f"Order Discount ({so.discount_percent}%)", dr=_q(0), cr=disc_amt, source="SalesOrderDiscount", pk=so.id)

    # 3. Receipts (Cr) - Combined from Invoices and Orders
    # SalesInvoice Receipts
    app_qs = (SalesInvoiceReceipt.objects
              .select_related("sales_invoice", "payment", "payment__bank_account")
              .filter(sales_invoice__business_id=business_id,
                      sales_invoice__customer_id=party_id))
    if date_from:
        app_qs = app_qs.filter(created_at__date__gte=date_from)
    if date_to:
        app_qs = app_qs.filter(created_at__date__lte=date_to)
    for app in app_qs:
        inv = app.sales_invoice
        source_note = f"Pay INV {inv.invoice_no}"
        pay_method = app.payment.get_payment_method_display()
        note = f"({pay_method})"
        yield LedgerRow(
            date=_as_date(app.created_at),
            ref=source_note,
            note=note,
            dr=_q(0), cr=_q(app.amount),
            source="SalesInvoiceReceipt", pk=app.id,
            allocations=[{"target": f"INV #{inv.invoice_no}", "amount": _q(app.amount)}],
        )

    # SalesOrder Receipts
    so_app_qs = (SalesOrderReceipt.objects
                 .select_related("sales_order", "payment", "payment__bank_account")
                 .filter(sales_order__business_id=business_id,
                         sales_order__customer_id=party_id)
                 .exclude(sales_order__status=SalesOrder.Status.CANCELLED))
    if date_from:
        so_app_qs = so_app_qs.filter(created_at__date__gte=date_from)
    if date_to:
        so_app_qs = so_app_qs.filter(created_at__date__lte=date_to)
    for app in so_app_qs:
        so = app.sales_order
        source_note = f"Pay SO #{so.id}"
        pay_method = app.payment.get_payment_method_display()
        note = f"({pay_method})"
        yield LedgerRow(
            date=_as_date(app.created_at),
            ref=source_note,
            note=note,
            dr=_q(0), cr=_q(app.amount),
            source="SalesOrderReceipt", pk=app.id,
            allocations=[{"target": f"SO #{so.id}", "amount": _q(app.amount)}],
        )

    # 4. Sales Returns (Cr)
    sr_qs = (SalesReturn.objects
             .filter(business_id=business_id, customer_id=party_id)
             .prefetch_related('items', 'items__product'))
    if date_from:
        sr_qs = sr_qs.filter(created_at__date__gte=date_from)
    if date_to:
        sr_qs = sr_qs.filter(created_at__date__lte=date_to)
    for sr in sr_qs:
        date_obj = _as_date(sr.created_at)
        ref = f"SR #{sr.id}"
        
        for it in sr.items.all():
            yield LedgerRow(
                date=date_obj, ref=ref, note="Return Item",
                dr=_q(0), cr=_q(it.line_total()),
                source="SalesReturnItem", pk=it.id,
                product_name=it.product.name,
                quantity=f"{it.quantity:.2f}",
                unit_price=f"{it.unit_price:.2f}"
            )
            
        if sr.tax_percent:
            tax_amt = _q(sr.total_amount * (sr.tax_percent / 100))
            yield LedgerRow(date=date_obj, ref=ref, note=f"Tax Adj ({sr.tax_percent}%)", dr=_q(0), cr=tax_amt, source="SalesReturnTax", pk=sr.id)
        if sr.discount_percent:
            disc_amt = _q(sr.total_amount * (sr.discount_percent / 100))
            yield LedgerRow(date=date_obj, ref=ref, note=f"Discount Adj ({sr.discount_percent}%)", dr=disc_amt, cr=_q(0), source="SalesReturnDiscount", pk=sr.id)

    # 5. Refunds paid to customer (Dr)
    rf_qs = (SalesReturnRefund.objects
             .select_related("sales_return")
             .filter(sales_return__business_id=business_id,
                     sales_return__customer_id=party_id))
    if date_from:
        rf_qs = rf_qs.filter(created_at__date__gte=date_from)
    if date_to:
        rf_qs = rf_qs.filter(created_at__date__lte=date_to)
    for rf in rf_qs:
        sr = rf.sales_return
        yield LedgerRow(
            date=_as_date(rf.created_at),
            ref=f"REFUND SR #{sr.id}",
            note="Refund to Customer",
            dr=_q(rf.amount), cr=_q(0),
            source="SalesReturnRefund", pk=rf.id,
        )

# ---------- SUPPLIER LEDGER ----------
def supplier_rows(
    business_id: int,
    party_id: int,
    date_from: Optional[date],
    date_to: Optional[date],
) -> Iterable[LedgerRow]:
    # 1. Purchase Orders (Cr)
    po_qs = (PurchaseOrder.objects
             .filter(business_id=business_id, supplier_id=party_id)
             .prefetch_related('items', 'items__product', 'items__uom', 'expenses'))
    if date_from:
        po_qs = po_qs.filter(created_at__date__gte=date_from)
    if date_to:
        po_qs = po_qs.filter(created_at__date__lte=date_to)
    
    for po in po_qs:
        date_obj = _as_date(po.created_at)
        ref = f"PO #{po.id}"
        
        # Line Items
        for it in po.items.all():
            uom_code = it.uom.code if it.uom else ""
            yield LedgerRow(
                date=date_obj, ref=ref, note="Purchase Item",
                dr=_q(0), cr=_q(it.total_cost()),
                source="PurchaseOrderItem", pk=it.id,
                product_name=it.product.name,
                quantity=f"{it.quantity:.2f} {uom_code}".strip(),
                unit_price=f"{it.unit_price:.2f}"
            )
            
        # Adjustments
        if po.tax_percent:
            tax_amt = _q(po.total_cost * (po.tax_percent / 100))
            yield LedgerRow(date=date_obj, ref=ref, note=f"Tax ({po.tax_percent}%)", dr=_q(0), cr=tax_amt, source="PurchaseOrderTax", pk=po.id)
        if po.discount_percent:
            disc_amt = _q(po.total_cost * (po.discount_percent / 100))
            yield LedgerRow(date=date_obj, ref=ref, note=f"Order Discount ({po.discount_percent}%)", dr=disc_amt, cr=_q(0), source="PurchaseOrderDiscount", pk=po.id)
            
        # Linked Expenses (Freight etc) that affect PO net total and thus supplier ledger if not paid instantly
        # NOTE: In this system, Expenses are usually separate transactions. 
        # But if they are added TO the PO and marked as part of net_total, they should show up.
        for ex in po.expenses.all():
            yield LedgerRow(
                date=_as_date(ex.date),
                ref=ref,
                note=f"Expense: {ex.get_category_display()}",
                dr=_q(0), cr=_q(ex.amount),
                source="PurchaseOrderExpense", pk=ex.id
            )

    # 2. Payments to supplier (Dr)
    pay_qs = (PurchaseOrderPayment.objects
              .select_related("purchase_order", "payment", "payment__bank_account")
              .filter(purchase_order__business_id=business_id,
                      purchase_order__supplier_id=party_id))
    if date_from:
        pay_qs = pay_qs.filter(created_at__date__gte=date_from)
    if date_to:
        pay_qs = pay_qs.filter(created_at__date__lte=date_to)
    for app in pay_qs:
        po = app.purchase_order
        source_note = f"Pay PO #{po.id}"
        pay_method = app.payment.get_payment_method_display()
        note = f"({pay_method})"
        yield LedgerRow(
            date=_as_date(app.created_at),
            ref=source_note,
            note=note,
            dr=_q(app.amount), cr=_q(0),
            source="PurchaseOrderPayment", pk=app.id,
            allocations=[{"target": f"PO #{po.id}", "amount": _q(app.amount)}],
        )

    # 3. Purchase Returns (Dr)
    pr_qs = (PurchaseReturn.objects
             .filter(business_id=business_id, supplier_id=party_id)
             .prefetch_related('items', 'items__product'))
    if date_from:
        pr_qs = pr_qs.filter(created_at__date__gte=date_from)
    if date_to:
        pr_qs = pr_qs.filter(created_at__date__lte=date_to)
    for pr in pr_qs:
        date_obj = _as_date(pr.created_at)
        ref = f"PR #{pr.id}"
        
        for it in pr.items.all():
            yield LedgerRow(
                date=date_obj, ref=ref, note="Purchase Return Item",
                dr=_q(it.total_cost()), cr=_q(0),
                source="PurchaseReturnItem", pk=it.id,
                product_name=it.product.name,
                quantity=f"{it.quantity:.2f}",
                unit_price=f"{it.unit_price:.2f}"
            )
            
        if pr.tax_percent:
            tax_amt = _q(pr.total_cost * (pr.tax_percent / 100))
            yield LedgerRow(date=date_obj, ref=ref, note=f"Tax Adj ({pr.tax_percent}%)", dr=tax_amt, cr=_q(0), source="PurchaseReturnTax", pk=pr.id)
        if pr.discount_percent:
            disc_amt = _q(pr.total_cost * (pr.discount_percent / 100))
            yield LedgerRow(date=date_obj, ref=ref, note=f"Discount Adj ({pr.discount_percent}%)", dr=_q(0), cr=disc_amt, source="PurchaseReturnDiscount", pk=pr.id)

    # 4. Refunds received from supplier (Cr)
    rf_qs = (PurchaseReturnRefund.objects
             .select_related("purchase_return")
             .filter(purchase_return__business_id=business_id,
                     purchase_return__supplier_id=party_id))
    if date_from:
        rf_qs = rf_qs.filter(created_at__date__gte=date_from)
    if date_to:
        rf_qs = rf_qs.filter(created_at__date__lte=date_to)
    for rf in rf_qs:
        pr = rf.purchase_return
        yield LedgerRow(
            date=_as_date(rf.created_at),
            ref=f"REFUND PR #{pr.id}",
            note="Refund from Supplier",
            dr=_q(0), cr=_q(rf.amount),
            source="PurchaseReturnRefund", pk=rf.id,
        )

# ---------- STAFF LEDGER ----------
# Policy (per your ask):
# - On the 1st of every month (from staff.salary_start), add a Credit = monthly_salary (salary payable).
# - When you record an Expense with category=SALARY for that staff, add a Debit = amount (salary paid).
def _staff_accrual_rows(
    business_id: int,
    staff: Staff,
    date_from: Optional[date],
    date_to: Optional[date],
) -> Iterable[LedgerRow]:
    if not staff.monthly_salary or staff.monthly_salary <= 0:
        return
    if not staff.salary_start:
        return

    # define range we will synthesize over
    start = _month_start(staff.salary_start)
    end = _month_start(_as_date(date_to or timezone.localdate()))
    if date_from:
        # we still need accruals back in time to compute B/F; the caller handles B/F,
        # so only generate visible rows inside the filter window.
        range_start = _month_start(max(date_from, start))
    else:
        range_start = start

    for ms in _iter_month_starts(range_start, end):
        yield LedgerRow(
            date=ms,
            ref=f"ACCRUAL {ms.strftime('%b %Y')}",
            note="Monthly Salary Accrual",
            dr=_q(0), cr=_q(staff.monthly_salary),
            source="SalaryAccrual",
        )

def _staff_payment_rows(
    business_id: int,
    staff: Staff,
    date_from: Optional[date],
    date_to: Optional[date],
) -> Iterable[LedgerRow]:
    # Include expenses tied to this staff where:
    # - category is SALARY
    # - and business matches the selected business OR is NULL (legacy rows)
    ex_qs = Expense.objects.filter(
        staff_id=staff.id,
        category=ExpenseCategory.SALARY,
    ).filter(
        Q(business_id=business_id) | Q(business__isnull=True)
    )

    if date_from:
        ex_qs = ex_qs.filter(date__gte=date_from)
    if date_to:
        ex_qs = ex_qs.filter(date__lte=date_to)

    for ex in ex_qs.only("id", "date", "amount", "description", "reference"):
        note = ex.description or "Salary Payment"
        if ex.reference:
            note = f"{note} (Ref: {ex.reference})"
        yield LedgerRow(
            date=_as_date(ex.date),
            ref=f"EXP#{ex.id}",
            note=note,
            dr=_q(ex.amount), cr=_q(0),
            source="Expense", pk=ex.id,
        )

def staff_rows(
    business_id: int,
    staff_id: int,
    date_from: Optional[date],
    date_to: Optional[date],
) -> Iterable[LedgerRow]:
    staff = Staff.objects.get(pk=staff_id)
    # visible rows only in window
    for r in _staff_accrual_rows(business_id, staff, date_from, date_to):
        yield r
    for r in _staff_payment_rows(business_id, staff, date_from, date_to):
        yield r

# ---------- Facade ----------
def opening_balance(kind: LedgerKind, entity, business_id: Optional[int] = None) -> Tuple[Decimal, str]:
    """
    Party.opening_balance applies for customers/suppliers.
    For staff we keep it zero unless you add a field later.
    
    Returns: (amount, side) where side is 'Dr' or 'Cr'
    - Uses entity.opening_balance_side to determine direction
    - Defaults to 'Dr' if not specified
    """
    if kind in ("customer", "supplier") and isinstance(entity, Party):
        # Business logic:
        # If business_id is passed, show OB only if it matches party.default_business
        if business_id is not None:
             # If party has a specific default_business, only show there.
             # If default_business is None, it's a global party - show in all businesses.
             if entity.default_business_id and entity.default_business_id != business_id:
                  return Decimal("0.00"), 'Dr'

        ob = _q(entity.opening_balance)
        side = getattr(entity, 'opening_balance_side', 'Dr') or 'Dr'
        return ob, side
    return Decimal("0.00"), 'Dr'

def _all_rows_full_range(
    kind: LedgerKind, business_id: int, entity_id: int
) -> Tuple[list[LedgerRow], object]:
    if kind == "customer":
        party = Party.objects.get(pk=entity_id)
        rows = list(customer_rows(business_id, party.id, None, None))
        
        # Always include supplier transactions too if they exist
        rows.extend(list(supplier_rows(business_id, party.id, None, None)))
            
        ob, side = opening_balance(kind, party, business_id=business_id)
        if ob > 0:
            # Use opening_balance_date if set, otherwise fall back to created_at
            ob_date = party.opening_balance_date or _as_date(party.created_at)
            if side == 'Dr':
                opening = [LedgerRow(date=ob_date, ref="OPENING", note="Opening Balance (Dr)",
                                   dr=ob, cr=_q(0), source="Opening")]
            else:  # Cr
                opening = [LedgerRow(date=ob_date, ref="OPENING", note="Opening Balance (Cr)",
                                   dr=_q(0), cr=ob, source="Opening")]
        else:
            opening = []
        entity = party

    elif kind == "supplier":
        party = Party.objects.get(pk=entity_id)
        rows = list(supplier_rows(business_id, party.id, None, None))
        
        # Always include customer transactions too if they exist
        rows.extend(list(customer_rows(business_id, party.id, None, None)))
            
        ob, side = opening_balance(kind, party, business_id=business_id)
        if ob > 0:
            # Use opening_balance_date if set, otherwise fall back to created_at
            ob_date = party.opening_balance_date or _as_date(party.created_at)
            if side == 'Dr':
                opening = [LedgerRow(date=ob_date, ref="OPENING", note="Opening Balance (Dr)",
                                   dr=ob, cr=_q(0), source="Opening")]
            else:  # Cr
                opening = [LedgerRow(date=ob_date, ref="OPENING", note="Opening Balance (Cr)",
                                   dr=_q(0), cr=ob, source="Opening")]
        else:
            opening = []
        entity = party

    else:  # staff
        staff = Staff.objects.get(pk=entity_id)
        # full-range rows for B/F math
        rows = list(_staff_accrual_rows(business_id, staff, None, None)) + \
               list(_staff_payment_rows(business_id, staff, None, None))
        opening = []  # no static opening for staff by default
        entity = staff

    all_rows = opening + rows
    all_rows.sort(key=lambda r: (r.date, r.pk or 0))
    return all_rows, entity

def _brought_forward(rows: list[LedgerRow], as_of: date) -> Optional[LedgerRow]:
    """
    Compute balance of rows strictly before as_of; return a B/F row if non-zero.
    Excludes opening balance rows - only calculates from transactions.
    """
    # Filter out opening balance rows - we only want transactions for B/F
    transaction_rows = [r for r in rows if r.source != "Opening" and r.date < as_of]
    
    pre_dr = _q(sum((r.dr for r in transaction_rows), Decimal("0.00")))
    pre_cr = _q(sum((r.cr for r in transaction_rows), Decimal("0.00")))
    bal = _q(pre_dr - pre_cr)  # +ve Dr, -ve Cr
    if bal == Decimal("0.00"):
        return None
    if bal > 0:
        return LedgerRow(date=as_of, ref="B/F", note="Balance brought forward", dr=bal, cr=_q(0), source="B/F")
    else:
        return LedgerRow(date=as_of, ref="B/F", note="Balance brought forward", dr=_q(0), cr=abs(bal), source="B/F")

def build_ledger(
    kind: LedgerKind,
    business_id: int,
    entity_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
):
    """
    Returns (rows_sorted, totals: dict, entity)
    - Supports date filtering.
    - Opening balance ALWAYS shows as separate row with its date.
    - B/F includes only transactions before date_from (excluding opening).
    - Staff ledger includes monthly Credit accruals + Debit salary expenses.
    """
    # assemble full history once (for correct B/F)
    full_rows, entity = _all_rows_full_range(kind, business_id, entity_id)
    
    # Separate opening balance from other transactions
    opening_rows = [r for r in full_rows if r.source == "Opening"]
    transaction_rows = [r for r in full_rows if r.source != "Opening"]
    
    # filter transactions to window
    if date_from:
        vis_transaction_rows = [r for r in transaction_rows if r.date >= date_from]
    else:
        vis_transaction_rows = transaction_rows[:]
    if date_to:
        vis_transaction_rows = [r for r in vis_transaction_rows if r.date <= date_to]
    
    # Calculate B/F from transactions only (excluding opening balance)
    # B/F = transactions before date_from
    vis_rows = []
    if date_from:
        bf = _brought_forward(transaction_rows, date_from)
        if bf:
            vis_rows.append(bf)
    
    # ALWAYS add opening balance row(s) if they exist
    # Opening balance should always be visible in the ledger
    vis_rows.extend(opening_rows)
    
    # Add filtered transactions
    vis_rows.extend(vis_transaction_rows)
    
    # final sort
    vis_rows.sort(key=lambda r: (r.date, r.pk or 0))
    
    # Progressive Running Balance
    curr_bal = Decimal("0.00")
    for r in vis_rows:
        curr_bal += (r.dr - r.cr)
        r.run_amount = abs(curr_bal)
        r.run_side = "Dr" if curr_bal > 0 else ("Cr" if curr_bal < 0 else "")

    total_dr = _q(sum((r.dr for r in vis_rows), Decimal("0.00")))
    total_cr = _q(sum((r.cr for r in vis_rows), Decimal("0.00")))
    balance = _q(total_dr - total_cr)  # positive → Dr, negative → Cr
    
    return vis_rows, {
        "total_dr": total_dr,
        "total_cr": total_cr,
        "balance": balance,
        "balance_abs": balance.copy_abs() if hasattr(balance, "copy_abs") else abs(balance),
        "balance_side": "Dr" if balance > 0 else ("Cr" if balance < 0 else ""),
    }, entity


