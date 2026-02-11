from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.db.models import Sum, F, Q, Case, When, DecimalField
from decimal import Decimal
from .models import (
    Business, BusinessSummary, SummaryStats,
    SalesOrder, SalesOrderReceipt,
    PurchaseOrder, PurchaseOrderPayment,
    Payment, Expense, Product,
    StockMove, SalesReturn, SalesReturnRefund,
    PurchaseReturn, PurchaseReturnRefund,
    Party, BankMovement, SalesInvoice, BankAccount
)
from django.utils import timezone
from barkat.services.balance_service import get_party_balances
from django.db import transaction

def _get_summary_stats():
    return SummaryStats.get_stats()

# ---------------------------------------------------------
# SummaryStats Atomic Updates (Real-Time Global Statistics)
# ---------------------------------------------------------

def capture_orig(instance, fields):
    if instance.pk:
        try:
            orig = instance.__class__.objects.only(*fields).get(pk=instance.pk)
            for f in fields:
                setattr(instance, f'_orig_{f}', getattr(orig, f))
        except instance.__class__.DoesNotExist:
            for f in fields:
                setattr(instance, f'_orig_{f}', None)
    else:
        for f in fields:
            setattr(instance, f'_orig_{f}', None)

@receiver(post_save, sender=SummaryStats)
def ensure_singleton(sender, instance, **kwargs):
    if instance.pk != 1:
        instance.delete()
        raise ValueError("SummaryStats is a singleton and must have pk=1")

# 1. SalesOrder Signals (Receivables)
@receiver(pre_save, sender=SalesOrder)
def so_pre_save(sender, instance, **kwargs):
    capture_orig(instance, ['net_total', 'status', 'business_id'])

@receiver(post_save, sender=SalesOrder)
def so_post_save(sender, instance, created, **kwargs):
    old_total = getattr(instance, '_orig_net_total', Decimal("0.00")) or Decimal("0.00")
    old_status = getattr(instance, '_orig_status', None)
    
    new_total = instance.net_total or Decimal("0.00")
    new_status = instance.status

    # Only count if not cancelled
    val_old = old_total if old_status != 'CANCELLED' else Decimal("0.00")
    val_new = new_total if new_status != 'CANCELLED' else Decimal("0.00")
    
    diff = val_new - val_old
    if diff != 0:
        SummaryStats.objects.filter(pk=1).update(total_receivables=F('total_receivables') + diff)

    # Business summary update
    old_biz_id = getattr(instance, '_orig_business_id', None)
    new_biz_id = instance.business_id
    if old_biz_id and old_biz_id != new_biz_id:
        update_business_summary(old_biz_id)
    update_business_summary(new_biz_id)

@receiver(post_delete, sender=SalesOrder)
def so_post_delete(sender, instance, **kwargs):
    if instance.status != 'CANCELLED':
        SummaryStats.objects.filter(pk=1).update(total_receivables=F('total_receivables') - (instance.net_total or 0))
    update_business_summary(instance.business_id)

# 2. PurchaseOrder Signals (Payables)
@receiver(pre_save, sender=PurchaseOrder)
def po_pre_save(sender, instance, **kwargs):
    capture_orig(instance, ['net_total', 'status', 'business_id'])

@receiver(post_save, sender=PurchaseOrder)
def po_post_save(sender, instance, created, **kwargs):
    old_total = getattr(instance, '_orig_net_total', Decimal("0.00")) or Decimal("0.00")
    old_status = getattr(instance, '_orig_status', None)
    
    new_total = instance.net_total or Decimal("0.00")
    new_status = instance.status

    val_old = old_total if old_status != 'CANCELLED' else Decimal("0.00")
    val_new = new_total if new_status != 'CANCELLED' else Decimal("0.00")
    
    diff = val_new - val_old
    if diff != 0:
        SummaryStats.objects.filter(pk=1).update(total_payables=F('total_payables') + diff)

    # Business summary update
    old_biz_id = getattr(instance, '_orig_business_id', None)
    new_biz_id = instance.business_id
    if old_biz_id and old_biz_id != new_biz_id:
        update_business_summary(old_biz_id)
    update_business_summary(new_biz_id)

@receiver(post_delete, sender=PurchaseOrder)
def po_post_delete(sender, instance, **kwargs):
    if instance.status != 'CANCELLED':
        SummaryStats.objects.filter(pk=1).update(total_payables=F('total_payables') - (instance.net_total or 0))
    update_business_summary(instance.business_id)

# 3. Payment Signals (Receivables/Payables reduction + Cash In Hand)
@receiver(pre_save, sender=Payment)
def pay_pre_save(sender, instance, **kwargs):
    capture_orig(instance, ['amount', 'direction', 'payment_method', 'bank_account', 'is_deleted', 'business_id'])

@receiver(post_save, sender=Payment)
def pay_post_save(sender, instance, created, **kwargs):
    def get_impact(obj):
        if not obj or getattr(obj, 'is_deleted', False): return (0, 0, 0)
        
        amt = obj.amount or Decimal("0.00")
        dr = obj.direction # 'in' or 'out'
        
        # Receivables/Payables impact
        # IN = money from customer/supplier. OUT = money to customer/supplier.
        # Direction 'in' (Collection): Reduces Receivables (if customer)
        # Direction 'out' (Payment): Reduces Payables (if supplier)
        rec_impact = -amt if dr == 'in' else 0
        pay_impact = -amt if dr == 'out' else 0
        
        # Cash impact logic
        is_cash = False
        if obj.payment_method == 'cash':
            is_cash = True
        elif obj.payment_method == 'bank' and obj.bank_account and obj.bank_account.account_type == 'CASH':
            # Assuming BankAccount also has is_active/is_deleted if we're following the pattern
            if getattr(obj.bank_account, 'is_active', True) and not getattr(obj.bank_account, 'is_deleted', False):
                is_cash = True
        
        cash_impact = 0
        if is_cash:
            cash_impact = amt if dr == 'in' else -amt
            
        return (rec_impact, pay_impact, cash_impact)

    # We treat the old state as a "mock" object for impacts
    class MockPay:
        pass
    
    old_obj = MockPay()
    old_obj.amount = getattr(instance, '_orig_amount', 0)
    old_obj.direction = getattr(instance, '_orig_direction', None)
    old_obj.payment_method = getattr(instance, '_orig_payment_method', None)
    old_obj.bank_account = getattr(instance, '_orig_bank_account', None)
    old_obj.is_deleted = getattr(instance, '_orig_is_deleted', False)
    
    old_rec, old_pay, old_cash = get_impact(old_obj)
    new_rec, new_pay, new_cash = get_impact(instance)
    
    diff_rec = new_rec - old_rec
    diff_pay = new_pay - old_pay
    diff_cash = new_cash - old_cash
    
    if diff_rec != 0 or diff_pay != 0 or diff_cash != 0:
        SummaryStats.objects.filter(pk=1).update(
            total_receivables=F('total_receivables') + diff_rec,
            total_payables=F('total_payables') + diff_pay,
            cash_in_hand=F('cash_in_hand') + diff_cash
        )

    # Business summary update
    old_biz_id = getattr(instance, '_orig_business_id', None)
    new_biz_id = instance.business_id
    if old_biz_id and old_biz_id != new_biz_id:
        update_business_summary(old_biz_id)
    update_business_summary(new_biz_id)

@receiver(post_delete, sender=Payment)
def pay_post_delete(sender, instance, **kwargs):
    # Reverse the impact
    # Reuse impact logic
    def get_impact(obj):
        if getattr(obj, 'is_deleted', False): return (0, 0, 0)
        amt = obj.amount or Decimal("0.00")
        dr = obj.direction
        rec = -amt if dr == 'in' else 0
        pay = -amt if dr == 'out' else 0
        is_cash = (obj.payment_method == 'cash' or 
                  (obj.payment_method == 'bank' and obj.bank_account and obj.bank_account.account_type == 'CASH'))
        cash = (amt if dr == 'in' else -amt) if is_cash else 0
        return (rec, pay, cash)
    
    r, p, c = get_impact(instance)
    SummaryStats.objects.filter(pk=1).update(
        total_receivables=F('total_receivables') - r,
        total_payables=F('total_payables') - p,
        cash_in_hand=F('cash_in_hand') - c
    )
    update_business_summary(instance.business_id)

# 4. Expense Signals (Cash In Hand)
@receiver(pre_save, sender=Expense)
def exp_pre_save(sender, instance, **kwargs):
    capture_orig(instance, ['amount', 'payment_source', 'is_deleted', 'business_id'])

@receiver(post_save, sender=Expense)
def exp_post_save(sender, instance, created, **kwargs):
    def get_cash_impact(obj):
        if not obj or getattr(obj, 'is_deleted', False): return 0
        amt = obj.amount or Decimal("0.00")
        # Expense is always OUT
        return -amt if obj.payment_source == 'cash' else 0

    class MockExp: pass
    old_obj = MockExp()
    old_obj.amount = getattr(instance, '_orig_amount', 0)
    old_obj.payment_source = getattr(instance, '_orig_payment_source', None)
    old_obj.is_deleted = getattr(instance, '_orig_is_deleted', False)
    
    old_c = get_cash_impact(old_obj)
    new_c = get_cash_impact(instance)
    
    diff = new_c - old_c
    if diff != 0:
        SummaryStats.objects.filter(pk=1).update(cash_in_hand=F('cash_in_hand') + diff)

    # Business summary update
    old_biz_id = getattr(instance, '_orig_business_id', None)
    new_biz_id = instance.business_id
    if old_biz_id and old_biz_id != new_biz_id:
        update_business_summary(old_biz_id)
    update_business_summary(new_biz_id)

@receiver(post_delete, sender=Expense)
def exp_post_delete(sender, instance, **kwargs):
    if not instance.is_deleted and instance.payment_source == 'cash':
        SummaryStats.objects.filter(pk=1).update(cash_in_hand=F('cash_in_hand') + (instance.amount or 0))
    update_business_summary(instance.business_id)

# 5. Party Signals (Opening Balance -> Receivables/Payables)
@receiver(pre_save, sender=Party)
def party_pre_save(sender, instance, **kwargs):
    capture_orig(instance, ['opening_balance', 'opening_balance_side', 'is_deleted'])

@receiver(post_save, sender=Party)
def party_post_save(sender, instance, created, **kwargs):
    def get_impact(obj):
        if not obj or getattr(obj, 'is_deleted', False): return (0, 0)
        bal = obj.opening_balance or Decimal("0.00")
        side = obj.opening_balance_side # 'Dr' or 'Cr'
        rec = bal if side == 'Dr' else 0
        pay = bal if side == 'Cr' else 0
        return (rec, pay)

    class MockParty: pass
    old_obj = MockParty()
    old_obj.opening_balance = getattr(instance, '_orig_opening_balance', 0)
    old_obj.opening_balance_side = getattr(instance, '_orig_opening_balance_side', 'Dr')
    old_obj.is_deleted = getattr(instance, '_orig_is_deleted', False)
    
    o_rec, o_pay = get_impact(old_obj)
    n_rec, n_pay = get_impact(instance)
    
    diff_rec = n_rec - o_rec
    diff_pay = n_pay - o_pay
    
    if diff_rec != 0 or diff_pay != 0:
        SummaryStats.objects.filter(pk=1).update(
            total_receivables=F('total_receivables') + diff_rec,
            total_payables=F('total_payables') + diff_pay
        )

@receiver(post_delete, sender=Party)
def party_post_delete(sender, instance, **kwargs):
    bal = instance.opening_balance or Decimal("0.00")
    if instance.opening_balance_side == 'Dr':
        SummaryStats.objects.filter(pk=1).update(total_receivables=F('total_receivables') - bal)
    else:
        SummaryStats.objects.filter(pk=1).update(total_payables=F('total_payables') - bal)

# 6. BankAccount Signals (Opening Balance -> Cash In Hand)
@receiver(pre_save, sender=BankAccount)
def bank_pre_save(sender, instance, **kwargs):
    capture_orig(instance, ['opening_balance', 'account_type', 'is_active'])

@receiver(post_save, sender=BankAccount)
def bank_post_save(sender, instance, created, **kwargs):
    def get_cash_impact(obj):
        if not obj or not getattr(obj, 'is_active', True): return 0
        if obj.account_type != BankAccount.CASH: return 0
        return obj.opening_balance or Decimal("0.00")

    class MockBank: pass
    old_obj = MockBank()
    old_obj.opening_balance = getattr(instance, '_orig_opening_balance', 0)
    old_obj.account_type = getattr(instance, '_orig_account_type', BankAccount.BANK)
    old_obj.is_active = getattr(instance, '_orig_is_active', True)
    
    old_c = get_cash_impact(old_obj)
    new_c = get_cash_impact(instance)
    
    diff = new_c - old_c
    if diff != 0:
        SummaryStats.objects.filter(pk=1).update(cash_in_hand=F('cash_in_hand') + diff)

@receiver(post_delete, sender=BankAccount)
def bank_post_delete(sender, instance, **kwargs):
    if instance.is_active and instance.account_type == BankAccount.CASH:
        SummaryStats.objects.filter(pk=1).update(cash_in_hand=F('cash_in_hand') - (instance.opening_balance or 0))

# --- Original Signals ---

@receiver(pre_save, sender=SalesReturn)
def sr_pre_save(sender, instance, **kwargs):
    capture_orig(instance, ['net_total', 'status'])

@receiver(post_save, sender=SalesReturn)
def sr_post_save(sender, instance, created, **kwargs):
    old_total = getattr(instance, '_orig_net_total', Decimal("0.00")) or Decimal("0.00")
    old_status = getattr(instance, '_orig_status', None)
    new_total = instance.net_total or Decimal("0.00")
    new_status = instance.status

    # Sales Return reduces Receivables
    val_old = old_total if old_status != 'CANCELLED' else Decimal("0.00")
    val_new = new_total if new_status != 'CANCELLED' else Decimal("0.00")
    
    diff = val_new - val_old
    if diff != 0:
        # Subtract from receivables
        SummaryStats.objects.filter(pk=1).update(total_receivables=F('total_receivables') - diff)

    update_business_summary(instance.business_id)

@receiver(post_delete, sender=SalesReturn)
def sr_post_delete(sender, instance, **kwargs):
    if instance.status != 'CANCELLED':
        SummaryStats.objects.filter(pk=1).update(total_receivables=F('total_receivables') + (instance.net_total or 0))
    update_business_summary(instance.business_id)


@receiver(pre_save, sender=PurchaseReturn)
def pr_pre_save(sender, instance, **kwargs):
    capture_orig(instance, ['net_total', 'status'])

@receiver(post_save, sender=PurchaseReturn)
def pr_post_save(sender, instance, created, **kwargs):
    old_total = getattr(instance, '_orig_net_total', Decimal("0.00")) or Decimal("0.00")
    old_status = getattr(instance, '_orig_status', None)
    new_total = instance.net_total or Decimal("0.00")
    new_status = instance.status

    # Purchase Return reduces Payables
    val_old = old_total if old_status != 'CANCELLED' else Decimal("0.00")
    val_new = new_total if new_status != 'CANCELLED' else Decimal("0.00")
    
    diff = val_new - val_old
    if diff != 0:
        # Subtract from payables
        SummaryStats.objects.filter(pk=1).update(total_payables=F('total_payables') - diff)

    update_business_summary(instance.business_id)

@receiver(post_delete, sender=PurchaseReturn)
def pr_post_delete(sender, instance, **kwargs):
    if instance.status != 'CANCELLED':
        SummaryStats.objects.filter(pk=1).update(total_payables=F('total_payables') + (instance.net_total or 0))
    update_business_summary(instance.business_id)


def update_business_summary(business_id):
    if not business_id:
        return

    from barkat.models import BusinessSummary
    from barkat.services.financial_logic import get_business_financials

    summary, created = BusinessSummary.objects.get_or_create(business_id=business_id)
    stats = get_business_financials(business_id)
    
    summary.cash_in_hand = stats['cash_in_hand']
    summary.bank_balance = stats['bank_balance']
    summary.inventory_value = stats['inventory_value']
    summary.total_receivables = stats['total_receivables']
    summary.total_payables = stats['total_payables']

    summary.save()

# --- Signal Receivers ---

@receiver(post_save, sender=SalesOrder)
@receiver(post_delete, sender=SalesOrder)
def on_so_change(sender, instance, **kwargs):
    update_business_summary(instance.business_id)
    if instance.customer_id: update_party_balance(instance.customer_id)

@receiver(post_save, sender=SalesInvoice)
@receiver(post_delete, sender=SalesInvoice)
def on_inv_change(sender, instance, **kwargs):
    update_business_summary(instance.business_id)
    if instance.customer_id: update_party_balance(instance.customer_id)

@receiver(post_save, sender=PurchaseOrder)
@receiver(post_delete, sender=PurchaseOrder)
def on_po_change(sender, instance, **kwargs):
    update_business_summary(instance.business_id)
    if instance.supplier_id: update_party_balance(instance.supplier_id)

@receiver(post_save, sender=Payment)
@receiver(post_delete, sender=Payment)
def on_payment_change(sender, instance, **kwargs):
    update_business_summary(instance.business_id)
    if instance.party_id: update_party_balance(instance.party_id)

@receiver(post_save, sender=Expense)
@receiver(post_delete, sender=Expense)
def on_expense_change(sender, instance, **kwargs):
    update_business_summary(instance.business_id)

@receiver(pre_save, sender=Product)
def product_pre_save(sender, instance, **kwargs):
    capture_orig(instance, ['stock_qty', 'purchase_price', 'is_active', 'is_deleted'])

@receiver(post_save, sender=Product)
def on_product_change(sender, instance, created, **kwargs):
    def get_val(obj):
        if not obj or getattr(obj, 'is_deleted', False):
            return Decimal("0.00")
        qty = Decimal(str(obj.stock_qty or 0))
        price = Decimal(str(obj.purchase_price or 0))
        return qty * price

    class MockProd: pass
    old_obj = MockProd()
    old_obj.stock_qty = getattr(instance, '_orig_stock_qty', 0)
    old_obj.purchase_price = getattr(instance, '_orig_purchase_price', 0)
    old_obj.is_active = getattr(instance, '_orig_is_active', True)
    old_obj.is_deleted = getattr(instance, '_orig_is_deleted', False)
    
    old_val = get_val(old_obj)
    new_val = get_val(instance)
    
    diff = new_val - old_val
    if diff != 0:
        SummaryStats.objects.filter(pk=1).update(total_inventory_valuation=F('total_inventory_valuation') + diff)

    update_business_summary(instance.business_id)

@receiver(post_save, sender=StockMove)
def on_stock_move(sender, instance, **kwargs):
    if instance.status == 'POSTED':
        if instance.source_business_id: update_business_summary(instance.source_business_id)
        if instance.dest_business_id: update_business_summary(instance.dest_business_id)

@receiver(pre_save, sender=BankMovement)
def bm_pre_save(sender, instance, **kwargs):
    capture_orig(instance, ['amount', 'movement_type', 'business_id'])

@receiver(post_save, sender=BankMovement)
def bm_post_save(sender, instance, created, **kwargs):
    def get_cash_impact(obj):
        if not obj: return 0
        amt = obj.amount or Decimal("0.00")
        mtype = (obj.movement_type or "").lower()
        if mtype in ("deposit", "cash_deposit"):
            return -amt
        elif mtype in ("withdraw", "withdrawal", "cash_withdrawal"):
            return amt
        return 0

    class MockBM: pass
    old_obj = MockBM()
    old_obj.amount = getattr(instance, '_orig_amount', 0)
    old_obj.movement_type = getattr(instance, '_orig_movement_type', None)
    
    old_c = get_cash_impact(old_obj)
    new_c = get_cash_impact(instance)
    
    diff = new_c - old_c
    if diff != 0:
        SummaryStats.objects.filter(pk=1).update(cash_in_hand=F('cash_in_hand') + diff)

    # Business summary update
    if instance.business_id:
        update_business_summary(instance.business_id)
    if hasattr(instance, '_orig_business_id') and instance._orig_business_id and instance._orig_business_id != instance.business_id:
        update_business_summary(instance._orig_business_id)
    
    # Existing party balance update
    if instance.party_id: 
        update_party_balance(instance.party_id)
    
    # If linked to PO
    if instance.purchase_order_id:
        update_business_summary(instance.purchase_order.business_id)

@receiver(post_delete, sender=BankMovement)
def bm_post_delete(sender, instance, **kwargs):
    amt = instance.amount or Decimal("0.00")
    mtype = (instance.movement_type or "").lower()
    diff = 0
    if mtype in ("deposit", "cash_deposit"):
        diff = amt # Reverse negative impact
    elif mtype in ("withdraw", "withdrawal", "cash_withdrawal"):
        diff = -amt # Reverse positive impact
    
    if diff != 0:
        SummaryStats.objects.filter(pk=1).update(cash_in_hand=F('cash_in_hand') + diff)
    
    if instance.business_id:
        update_business_summary(instance.business_id)
    if instance.party_id: 
        update_party_balance(instance.party_id)
    if instance.purchase_order_id:
        update_business_summary(instance.purchase_order.business_id)


# ==========================================
# Party Balance Caching Signals (Optimization)
# ==========================================

def update_party_balance(party_id):
    """
    Recalculates and caches the party balance.
    """
    if not party_id:
        return
        
    qs = Party.objects.filter(pk=party_id)
    # Calculate global balance (business_id=None)
    qs = get_party_balances(qs) 
    
    party = qs.first()
    if party:
        net = party.net_balance or Decimal("0.00")
        
        # We must use update() to avoid triggering post_save signal recursion if we had one on Party
        # But currently we don't have a signal on Party save that triggers this.
        # Still, update() is cleaner for a single field update.
        Party.objects.filter(pk=party_id).update(
            cached_balance=net,
            cached_balance_updated_at=timezone.now()
        )

@receiver(post_save, sender=SalesOrder)
@receiver(post_delete, sender=SalesOrder)
def on_so_party_update(sender, instance, **kwargs):
    if instance.customer_id:
        update_party_balance(instance.customer_id)

@receiver(post_save, sender=SalesInvoice)
@receiver(post_delete, sender=SalesInvoice)
def on_inv_party_update(sender, instance, **kwargs):
    if instance.customer_id:
        update_party_balance(instance.customer_id)

@receiver(post_save, sender=PurchaseOrder)
@receiver(post_delete, sender=PurchaseOrder)
def on_po_party_update(sender, instance, **kwargs):
    if instance.supplier_id:
        update_party_balance(instance.supplier_id)

@receiver(post_save, sender=PurchaseReturn)
@receiver(post_delete, sender=PurchaseReturn)
def on_pr_party_update(sender, instance, **kwargs):
    if instance.supplier_id:
        update_party_balance(instance.supplier_id)

@receiver(post_save, sender=SalesReturn)
@receiver(post_delete, sender=SalesReturn)
def on_sr_party_update(sender, instance, **kwargs):
    if instance.customer_id:
        update_party_balance(instance.customer_id)

@receiver(post_save, sender=Payment)
@receiver(post_delete, sender=Payment)
def on_pay_party_update(sender, instance, **kwargs):
    if instance.party_id:
        update_party_balance(instance.party_id)

@receiver(post_save, sender=BankMovement)
@receiver(post_delete, sender=BankMovement)
def on_bm_party_update(sender, instance, **kwargs):
    # Only relevance if movement_type is CHEQUE_PAYMENT and party is set
    # Or generically if it affects party
    if instance.party_id:
        update_party_balance(instance.party_id)
