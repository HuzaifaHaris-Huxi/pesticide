
# =========================
# Unified Ledger Aggregation (Phase 4)
# =========================
def get_party_balances(qs, business_id=None):
    """
    Annotates the Party queryset with 'annotated_balance_abs' and 'annotated_balance_side'.
    Logic mirrors ledger.py strict dr/cr rules + Payment IN/OUT.
    
    Dr Components (Asset/Receivable):
      - SalesOrder (net_total, ~CANCELLED)
      - SalesInvoice (net_total)
      - PurchaseReturn (net_total)
      - Payment (amount) WHERE direction=OUT (We paid / Refund to Customer)
      - Opening Balance (if side='Dr')

    Cr Components (Liability/Payable):
      - PurchaseOrder (net_total)
      - SalesReturn (net_total)
      - Payment (amount) WHERE direction=IN (We received / Refund from Supplier)
      - Opening Balance (if side='Cr')
      
    Balances are calculated per Party. 
    If business_id is provided, filters transactions by business.
    """
    from django.db.models import Sum, Q, Case, When, F, Value, DecimalField
    from django.db.models.functions import Coalesce
    
    # 1. SalesOrder Dr
    so_filter = Q(sales_orders__status__in=["open", "fulfilled"])  # Exclude cancelled
    if business_id:
        so_filter &= Q(sales_orders__business_id=business_id)
    
    # 2. SalesInvoice Dr
    inv_filter = Q()
    if business_id:
        inv_filter &= Q(sales_invoices__business_id=business_id)
        
    # 3. PurchaseReturn Dr
    pr_filter = Q()
    if business_id:
        pr_filter &= Q(purchase_returns__business_id=business_id)
        
    # 4. Payment OUT Dr
    pay_out_filter = Q(payments__direction="out")
    if business_id:
        pay_out_filter &= Q(payments__business_id=business_id)
    else:
        # Exclude deleted businesses logic if needed? 
        # ledger_views implies explicit business check or all.
        # We'll stick to basic filter.
        pass

    # 5. PurchaseOrder Cr
    po_filter = Q()  # ledger.py doesn't filter status for POs in supplier_rows
    if business_id:
        po_filter &= Q(purchase_orders__business_id=business_id)
        
    # 6. SalesReturn Cr
    sr_filter = Q()
    if business_id:
        sr_filter &= Q(sales_returns__business_id=business_id)
        
    # 7. Payment IN Cr
    pay_in_filter = Q(payments__direction="in")
    if business_id:
        pay_in_filter &= Q(payments__business_id=business_id)

    # Helper for sum
    def _sum(field, filter_q):
        return Coalesce(Sum(field, filter=filter_q), Decimal("0.00"))

    qs = qs.annotate(
        # --- DR ---
        dr_so=_sum("sales_orders__net_total", so_filter),
        dr_inv=_sum("sales_invoices__net_total", inv_filter),
        dr_pr=_sum("purchase_returns__net_total", pr_filter),
        dr_pay=_sum("payments__amount", pay_out_filter),

        # --- CR ---
        cr_po=_sum("purchase_orders__net_total", po_filter),
        cr_sr=_sum("sales_returns__net_total", sr_filter),
        cr_pay=_sum("payments__amount", pay_in_filter),
    )
    
    # Now aggregate into total_dr / total_cr including opening balance
    # Opening balance is Party-level, so not filtered by business?
    # ledger.py _all_rows_full_range uses Party.opening_balance regardless of business_id?
    # Yes, opening_balance(kind, party) wraps entity.opening_balance.
    
    # However, if business_id is provided, should we include global opening balance?
    # Logic in LedgersListView lines 763/821 handles opening balance separately.
    # But usually OB is a single global starting point for the Party entity.
    # Let's include it.
    
    qs = qs.annotate(
        final_dr=F("dr_so") + F("dr_inv") + F("dr_pr") + F("dr_pay") + 
                 Case(When(opening_balance_side='Dr', then=F('opening_balance')), default=Decimal(0), output_field=DecimalField()),
        
        final_cr=F("cr_po") + F("cr_sr") + F("cr_pay") + 
                 Case(When(opening_balance_side='Cr', then=F('opening_balance')), default=Decimal(0), output_field=DecimalField()),
    )
    
    qs = qs.annotate(
        net_balance=F("final_dr") - F("final_cr")
    )
    
    return qs
