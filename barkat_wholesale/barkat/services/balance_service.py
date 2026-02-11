from decimal import Decimal
from django.db.models import OuterRef, Subquery, Sum, Q, F, Case, When, Value, DecimalField
from django.db.models.functions import Coalesce
from barkat.models import SalesOrder, SalesInvoice, PurchaseReturn, Payment, BankMovement, PurchaseOrder, SalesReturn

def get_party_balances(qs, business_id=None, exclude_so_ids=None, exclude_po_ids=None, date_to=None):
    """
    Annotates the Party queryset with 'net_balance', 'bal_amount', 'bal_side'.
    Uses Subquery to avoid Cartesian product issues with multiple Sum annotations.
    
    Args:
        qs: Party QuerySet
        business_id: Optional business ID to filter transactions
        exclude_so_ids: List/QuerySet of SalesOrder IDs to exclude (for Edit mode)
        exclude_po_ids: List/QuerySet of PurchaseOrder IDs to exclude (for Edit mode)
        date_to: Optional date to limit transactions (for historical reports)
    """

    # Helper for subqueries
    def _sub_sum(model, link_field, distinct_field, amount_field, extra_filter=None):
        sub_qs = model.objects.filter(**{link_field: OuterRef("pk")})
        
        # Unified: Exclude deleted/inactive transactions
        if hasattr(model, 'is_deleted'):
            sub_qs = sub_qs.filter(is_deleted=False)
        if hasattr(model, 'is_active'):
             sub_qs = sub_qs.filter(is_active=True)

        if business_id:
            # For BankMovement, business_id is on purchase_order
            if model == BankMovement:
                sub_qs = sub_qs.filter(Q(purchase_order__business_id=business_id) | Q(purchase_order__isnull=True))
            else:
                sub_qs = sub_qs.filter(business_id=business_id)
        
        # Apply strict ID exclusions if provided for specific models
        if model == SalesOrder and exclude_so_ids:
            sub_qs = sub_qs.exclude(id__in=exclude_so_ids)
        if model == PurchaseOrder and exclude_po_ids:
            sub_qs = sub_qs.exclude(id__in=exclude_po_ids)

        if date_to:
            if hasattr(model, 'date'):
                sub_qs = sub_qs.filter(date__lte=date_to)
            elif hasattr(model, 'created_at'):
                sub_qs = sub_qs.filter(created_at__date__lte=date_to)

        if extra_filter:
            sub_qs = sub_qs.filter(extra_filter)
        
        return Coalesce(
            Subquery(
                sub_qs.values(link_field)
                .annotate(total=Sum(amount_field))
                .values("total")
            ),
            Decimal("0.00"),
            output_field=DecimalField()
        )

    # 1. SalesOrder Dr (status != CANCELLED)
    # Link: customer_id
    dr_so = _sub_sum(
        SalesOrder, "customer_id", "id", "net_total", 
        extra_filter=~Q(status="cancelled")
    )
    
    # 2. SalesInvoice Dr
    # Link: customer_id
    dr_inv = _sub_sum(
        SalesInvoice, "customer_id", "id", "net_total"
    )
        
    # 3. PurchaseReturn Dr
    # Link: supplier_id
    dr_pr = _sub_sum(
        PurchaseReturn, "supplier_id", "id", "net_total"
    )
    
    # 4. Payment OUT Dr (We paid / Refund to Customer)
    # Link: party_id
    dr_pay = _sub_sum(
        Payment, "party_id", "id", "amount",
        extra_filter=Q(direction="out") & ~Q(cheque_status="pending")
    )
    
    # 5. BankMovement Dr (Cheque Payment) - For Suppliers
    # Link: party_id
    dr_bm_val = _sub_sum(
        BankMovement, "party_id", "id", "amount",
        extra_filter=Q(movement_type="cheque_payment")
    )

    # 6. PurchaseOrder Cr
    # Link: supplier_id
    cr_po = _sub_sum(
        PurchaseOrder, "supplier_id", "id", "net_total"
    )
        
    # 7. SalesReturn Cr
    # Link: customer_id
    cr_sr = _sub_sum(
        SalesReturn, "customer_id", "id", "net_total"
    )
        
    # 8. Payment IN Cr (We received / Refund from Supplier)
    # Link: party_id
    cr_pay = _sub_sum(
        Payment, "party_id", "id", "amount",
        extra_filter=Q(direction="in") & ~Q(cheque_status="pending")
    )

    qs = qs.annotate(
        # --- DR ---
        dr_so=dr_so,
        dr_inv=dr_inv,
        dr_pr=dr_pr,
        dr_pay=dr_pay,
        dr_bm_raw=dr_bm_val,
        
        # --- CR ---
        cr_po=cr_po,
        cr_sr=cr_sr,
        cr_pay=cr_pay,
    )

    qs = qs.annotate(dr_bm=Coalesce(F("dr_bm_raw"), Value(0, output_field=DecimalField())))
    
    qs = qs.annotate(
        final_dr=F("dr_so") + F("dr_inv") + F("dr_pr") + F("dr_pay") + F("dr_bm") +
                 Case(
                     When(
                         Q(opening_balance_side='Dr') & 
                         (Q(default_business_id=business_id) if business_id else Q(id__isnull=False)), 
                         then=F('opening_balance')
                     ), 
                     default=Decimal(0), 
                     output_field=DecimalField()
                 ),
        
        final_cr=F("cr_po") + F("cr_sr") + F("cr_pay") + 
                 Case(
                     When(
                         Q(opening_balance_side='Cr') & 
                         (Q(default_business_id=business_id) if business_id else Q(id__isnull=False)), 
                         then=F('opening_balance')
                     ), 
                     default=Decimal(0), 
                     output_field=DecimalField()
                 ),
    )
    
    qs = qs.annotate(
        net_balance=F("final_dr") - F("final_cr")
    )
    
    return qs
