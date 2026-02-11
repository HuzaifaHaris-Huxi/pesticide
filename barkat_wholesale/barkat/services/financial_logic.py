from decimal import Decimal
from django.db.models import Sum, Q, F, Case, When, DecimalField, ExpressionWrapper
from barkat.models import CashFlow, BankAccount, Product, Party
from barkat.services.balance_service import get_party_balances

def get_business_financials(business_id=None):
    """
    Unified calculation for core financial metrics.
    If business_id is None, calculates global totals across all active businesses.
    """
    # 1. Cash In Hand (Physical Cash + CASH-type BankAccounts)
    cash_in_hand_qs = CashFlow.objects.filter(
        Q(bank_account__isnull=True) | Q(bank_account__account_type=BankAccount.CASH)
    ).filter(is_deleted=False)
    
    if business_id:
        cash_in_hand_qs = cash_in_hand_qs.filter(business_id=business_id)
    
    cash_in_hand = cash_in_hand_qs.aggregate(
        t=Sum(Case(
            When(flow_type=CashFlow.IN, then=F('amount')),
            When(flow_type=CashFlow.OUT, then=-F('amount')),
            default=Decimal('0.00'),
            output_field=DecimalField()
        ))
    )['t'] or Decimal('0.00')

    # Add opening balances for CASH accounts
    cash_acc_opening_qs = BankAccount.objects.filter(
        account_type=BankAccount.CASH,
        is_active=True,
        is_deleted=False
    )
    if business_id:
        cash_acc_opening_qs = cash_acc_opening_qs.filter(business_id=business_id)
    
    cash_acc_opening = cash_acc_opening_qs.aggregate(s=Sum('opening_balance'))['s'] or Decimal('0.00')
    cash_in_hand += cash_acc_opening

    # 2. Bank Balance (Only BANK-type BankAccounts)
    bank_balance_qs = CashFlow.objects.filter(
        bank_account__isnull=False,
        bank_account__account_type=BankAccount.BANK
    ).filter(is_deleted=False)
    
    if business_id:
        bank_balance_qs = bank_balance_qs.filter(business_id=business_id)
        
    bank_balance = bank_balance_qs.aggregate(
        t=Sum(Case(
            When(flow_type=CashFlow.IN, then=F('amount')),
            When(flow_type=CashFlow.OUT, then=-F('amount')),
            default=Decimal('0.00'),
            output_field=DecimalField()
        ))
    )['t'] or Decimal('0.00')

    # Add opening balances for BANK accounts
    bank_acc_opening_qs = BankAccount.objects.filter(
        account_type=BankAccount.BANK,
        is_active=True,
        is_deleted=False
    )
    if business_id:
        bank_acc_opening_qs = bank_acc_opening_qs.filter(business_id=business_id)
        
    bank_acc_opening = bank_acc_opening_qs.aggregate(s=Sum('opening_balance'))['s'] or Decimal('0.00')
    bank_balance += bank_acc_opening

    # 3. Inventory Value
    inventory_qs = Product.objects.filter(is_deleted=False, is_active=True)
    if business_id:
        inventory_qs = inventory_qs.filter(business_id=business_id)
        
    inventory_value = inventory_qs.aggregate(
        total=Sum(
            ExpressionWrapper(
                F('purchase_price') * F('stock_qty'),
                output_field=DecimalField(max_digits=18, decimal_places=2)
            )
        )
    )['total'] or Decimal("0.00")

    # 4. Receivables & Payables
    party_qs = Party.objects.filter(is_deleted=False)
    # Note: get_party_balances takes care of business_id filtering internally if provided
    all_balances = get_party_balances(party_qs, business_id=business_id)
    
    agg = all_balances.aggregate(
        recv=Sum(Case(When(net_balance__gt=0, then=F('net_balance')), default=0, output_field=DecimalField())),
        pay=Sum(Case(When(net_balance__lt=0, then=-F('net_balance')), default=0, output_field=DecimalField()))
    )
    
    total_receivables = agg['recv'] or Decimal('0.00')
    total_payables = agg['pay'] or Decimal('0.00')

    return {
        'cash_in_hand': cash_in_hand,
        'bank_balance': bank_balance,
        'inventory_value': inventory_value,
        'total_receivables': total_receivables,
        'total_payables': total_payables,
        'net_worth': (cash_in_hand + bank_balance + inventory_value + total_receivables) - total_payables
    }
