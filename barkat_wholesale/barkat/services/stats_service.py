from decimal import Decimal
from django.db.models import Sum, Q, F
from barkat.models import (
    SummaryStats, SalesOrder, SalesInvoice, PurchaseOrder, 
    Payment, Expense, Product, SalesReturn, PurchaseReturn, 
    Party, BankAccount, BankMovement
)

def recompute_summary_stats():
    """
    Recomputes the singleton SummaryStats (pk=1) from all base records.
    Returns the updated object.
    """
    stats = SummaryStats.get_stats()
    
    # 1. Receivables
    # Rec = (SO + INV + Party Opening Dr) - (SR + Payments IN)
    so_total = SalesOrder.objects.filter(~Q(status='CANCELLED'), is_deleted=False).aggregate(s=Sum('net_total'))['s'] or Decimal("0.00")
    inv_total = SalesInvoice.objects.filter(~Q(status='void'), is_deleted=False).aggregate(s=Sum('net_total'))['s'] or Decimal("0.00")
    party_dr = Party.objects.filter(opening_balance_side='Dr', is_deleted=False).aggregate(s=Sum('opening_balance'))['s'] or Decimal("0.00")
    
    sr_total = SalesReturn.objects.filter(~Q(status='CANCELLED'), is_deleted=False).aggregate(s=Sum('net_total'))['s'] or Decimal("0.00")
    pay_in = Payment.objects.filter(direction='in', is_deleted=False).exclude(cheque_status='pending').aggregate(s=Sum('amount'))['s'] or Decimal("0.00")
    
    stats.total_receivables = (so_total + inv_total + party_dr) - (sr_total + pay_in)
    
    # 2. Payables
    # Pay = (PO + Party Opening Cr) - (PR + Payments OUT)
    po_total = PurchaseOrder.objects.filter(~Q(status='CANCELLED'), is_deleted=False).aggregate(s=Sum('net_total'))['s'] or Decimal("0.00")
    party_cr = Party.objects.filter(opening_balance_side='Cr', is_deleted=False).aggregate(s=Sum('opening_balance'))['s'] or Decimal("0.00")
    
    pr_total = PurchaseReturn.objects.filter(~Q(status='CANCELLED'), is_deleted=False).aggregate(s=Sum('net_total'))['s'] or Decimal("0.00")
    pay_out = Payment.objects.filter(direction='out', is_deleted=False).exclude(cheque_status='pending').aggregate(s=Sum('amount'))['s'] or Decimal("0.00")
    
    stats.total_payables = (po_total + party_cr) - (pr_total + pay_out)
    
    # 3. Cash In Hand
    # Filter for cash-like payment methods
    cash_q = Q(payment_method='cash') | (Q(payment_method='bank') & Q(bank_account__account_type='CASH'))
    
    pay_in_cash = Payment.objects.filter(cash_q, direction='in', is_deleted=False).exclude(cheque_status='pending').aggregate(s=Sum('amount'))['s'] or Decimal("0.00")
    pay_out_cash = Payment.objects.filter(cash_q, direction='out', is_deleted=False).exclude(cheque_status='pending').aggregate(s=Sum('amount'))['s'] or Decimal("0.00")
    
    exp_cash = Expense.objects.filter(payment_source='cash', is_deleted=False).aggregate(s=Sum('amount'))['s'] or Decimal("0.00")
    bank_opening_cash = BankAccount.objects.filter(account_type='CASH', is_active=True).aggregate(s=Sum('opening_balance'))['s'] or Decimal("0.00")
    
    # BankMovement Cash Impacts
    # Deposit (Cash -> Bank) decreases cash
    bm_deposit = BankMovement.objects.filter(movement_type__iexact='deposit').aggregate(s=Sum('amount'))['s'] or Decimal("0.00")
    bm_cash_deposit = BankMovement.objects.filter(movement_type__iexact='cash_deposit').aggregate(s=Sum('amount'))['s'] or Decimal("0.00")
    
    # Withdrawal (Bank -> Cash) increases cash
    bm_withdraw = BankMovement.objects.filter(movement_type__iexact='withdraw').aggregate(s=Sum('amount'))['s'] or Decimal("0.00")
    bm_cash_withdraw = BankMovement.objects.filter(movement_type__iexact='cash_withdrawal').aggregate(s=Sum('amount'))['s'] or Decimal("0.00")
    
    stats.cash_in_hand = (pay_in_cash + bank_opening_cash + bm_withdraw + bm_cash_withdraw) - (pay_out_cash + exp_cash + bm_deposit + bm_cash_deposit)
    
    # 4. Inventory Valuation
    # Standard: Qty * Price
    stats.total_inventory_valuation = Product.objects.filter(is_deleted=False, is_active=True).annotate(
        val=F('stock_qty') * F('purchase_price')
    ).aggregate(s=Sum('val'))['s'] or Decimal("0.00")
    
    stats.save()
    return stats
