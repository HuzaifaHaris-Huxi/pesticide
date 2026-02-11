# barkat/services/business_summary_v2.py
"""
Comprehensive Business Summary Report Service
Calculates opening balance, sales, purchases, expenses, receipts, payments, and closing balance
"""
from decimal import Decimal
from datetime import date
from django.db.models import Sum, Q, F, Case, When, DecimalField
from django.utils import timezone
from typing import Dict, Any, Optional

from barkat.models import (
    Business, Payment, SalesOrder, SalesInvoice, PurchaseOrder, 
    Expense, CashFlow, BankAccount, BankMovement,
    SalesReturn, PurchaseReturn
)


class BusinessSummaryReportV2:
    """
    Generate comprehensive business summary for a given date range
    """
    
    def __init__(self, business: Business, start_date: date, end_date: date):
        self.business = business
        self.start_date = start_date
        self.end_date = end_date
        self._cache = {}
    
    def generate_full_report(self) -> Dict[str, Any]:
        """
        Generate complete business summary report
        Returns a dictionary with all financial metrics
        """
        return {
            'business': self.business,
            'period': {
                'start_date': self.start_date,
                'end_date': self.end_date,
            },
            'opening_balance': self.get_opening_balance(),
            'sales': self.get_sales_summary(),
            'purchases': self.get_purchases_summary(),
            'expenses': self.get_expenses_summary(),
            'receipts': self.get_receipts_summary(),
            'payments_made': self.get_payments_summary(),
            'deposits': self.get_deposits_summary(),
            'current_position': self.get_current_position(),
            'closing_balance': self.get_closing_balance(),
        }
    
    # ========================================
    # OPENING BALANCE
    # ========================================
    
    def get_opening_balance(self) -> Dict[str, Decimal]:
        """
        Calculate opening balance (before start_date)
        """
        # Cash opening balance
        cash_opening = self._calculate_cash_balance(before_date=self.start_date)
        
        # Bank opening balances
        bank_accounts = BankAccount.objects.filter(is_active=True)
        bank_balances = {}
        total_bank = Decimal('0.00')
        
        for acc in bank_accounts:
            balance = self._calculate_bank_balance(acc, before_date=self.start_date)
            bank_balances[acc.name] = balance
            total_bank += balance
        
        total_opening = cash_opening + total_bank
        
        return {
            'cash': cash_opening,
            'bank_accounts': bank_balances,
            'total_bank': total_bank,
            'total': total_opening,
        }
    
    # ========================================
    # SALES SUMMARY
    # ========================================
    
    def get_sales_summary(self) -> Dict[str, Any]:
        """
        Complete sales summary with payment breakdown
        """
        # Sales Orders
        sales_orders = SalesOrder.objects.filter(
            business=self.business,
            created_at__date__gte=self.start_date,
            created_at__date__lte=self.end_date,
            is_deleted=False
        )
        
        # Sales Invoices (if you use them separately)
        sales_invoices = SalesInvoice.objects.filter(
            business=self.business,
            invoice_date__gte=self.start_date,
            invoice_date__lte=self.end_date,
            is_deleted=False
        )
        
        # Total sales amount
        so_total = sales_orders.aggregate(total=Sum('net_total'))['total'] or Decimal('0.00')
        si_total = sales_invoices.aggregate(total=Sum('net_total'))['total'] or Decimal('0.00')
        total_sales = so_total + si_total
        
        # Sales Returns (Credit Note)
        sales_returns = SalesReturn.objects.filter(
            business=self.business,
            date__gte=self.start_date,
            date__lte=self.end_date,
            is_deleted=False
        )
        total_returns = sales_returns.aggregate(total=Sum('net_total'))['total'] or Decimal('0.00')

        # Refunds (Payments OUT to customers)
        refunds = Payment.objects.filter(
            business=self.business,
            direction=Payment.OUT,
            date__gte=self.start_date,
            date__lte=self.end_date,
            is_deleted=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        # Receipts breakdown (money actually received)
        receipts = self._get_sales_receipts_breakdown()
        
        # Calculate credit (outstanding)
        # Outstanding = (Sales + Refunds) - (Receipts + Returns)
        total_received = receipts['total_received']
        credit_outstanding = (total_sales + refunds) - (total_received + total_returns)
        
        return {
            'total_sales_amount': total_sales,
            'sales_orders_total': so_total,
            'sales_invoices_total': si_total,
            'total_returns': total_returns,
            'total_refunds': refunds,
            'receipts': receipts,
            'total_received': total_received,
            'credit_outstanding': credit_outstanding,
            'receipt_percentage': (total_received / (total_sales - total_returns) * 100) if (total_sales - total_returns) > 0 else Decimal('0.00'),
        }
    
    def _get_sales_receipts_breakdown(self) -> Dict[str, Any]:
        """
        Breakdown of how sales receipts were received
        """
        # Get all IN payments (receipts) for this business in period
        receipts = Payment.objects.filter(
            business=self.business,
            direction=Payment.IN,
            date__gte=self.start_date,
            date__lte=self.end_date,
            is_deleted=False
        )
        
        # Cash receipts
        cash_receipts = receipts.filter(
            payment_method=Payment.PaymentMethod.CASH
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Bank transfer receipts
        bank_receipts = receipts.filter(
            payment_method=Payment.PaymentMethod.BANK
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Cheque receipts - pending
        cheque_pending = receipts.filter(
            payment_method=Payment.PaymentMethod.CHEQUE,
            cheque_status=Payment.ChequeStatus.PENDING
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Cheque receipts - deposited
        cheque_deposited = receipts.filter(
            payment_method=Payment.PaymentMethod.CHEQUE,
            cheque_status=Payment.ChequeStatus.DEPOSITED
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        total_cheques = cheque_pending + cheque_deposited
        total_received = cash_receipts + bank_receipts + total_cheques
        
        return {
            'cash': cash_receipts,
            'bank_transfer': bank_receipts,
            'cheque_pending': cheque_pending,
            'cheque_deposited': cheque_deposited,
            'total_cheques': total_cheques,
            'total_received': total_received,
        }
    
    # ========================================
    # PURCHASES SUMMARY
    # ========================================
    
    def get_purchases_summary(self) -> Dict[str, Any]:
        """
        Complete purchases summary with payment breakdown
        """
        # Purchase Orders in period
        purchase_orders = PurchaseOrder.objects.filter(
            business=self.business,
            created_at__date__gte=self.start_date,
            created_at__date__lte=self.end_date,
            is_deleted=False
        )
        
        # Total purchases amount
        total_purchases = purchase_orders.aggregate(
            total=Sum('net_total')
        )['total'] or Decimal('0.00')
        
        # Purchase Returns (Debit Note)
        purchase_returns = PurchaseReturn.objects.filter(
            business=self.business,
            date__gte=self.start_date,
            date__lte=self.end_date,
            is_deleted=False
        )
        total_returns = purchase_returns.aggregate(total=Sum('net_total'))['total'] or Decimal('0.00')

        # Refunds (Payments IN from vendors)
        refunds = Payment.objects.filter(
            business=self.business,
            direction=Payment.IN,
            date__gte=self.start_date,
            date__lte=self.end_date,
            is_deleted=False,
            # Ensure we are capturing vendor refunds, not customer receipts
            # Usually Payment.IN is Customer Receipt. To flag Vendor Refund, logic usually relies on Applied Return.
            # But here we filter purely by direction for aggregate?
            # Dangerous. Payment.IN includes ALL receipts (Sales).
            # Vendor Refund is rare.
            # To isolate Vendor Refunds: Payment.IN AND applied_purchase_returns IS NOT NULL.
            applied_purchase_returns__isnull=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        # Payments breakdown (money actually paid)
        payments = self._get_purchase_payments_breakdown()
        
        # Calculate payables (outstanding)
        # Payables = (Purchases + Refunds_IN?? No.)
        # Payables (Cr Side): Purchases.
        # Reduced by: Payments (Dr), Returns (Dr), Refunds (Dr?? No).
        # Refund FROM Vendor (IN) -> Adds to Cash, Reduces Payables? No.
        # If Vendor pays us back, it means we overpaid or returned goods.
        # If we returned goods (Dr Payable), and they paid us (Cr Payable?? No. Debit Cash, Credit Payable).
        # So Refund IN INCREASES Payable (restores availability) or acts as Settlement of Return?
        # Standard: Return (Dr Payable). Refund (Dr Cash, Cr Payable).
        # So Net Effect on Payable:
        # Purchase (Cr)
        # Payment (Dr)
        # Return (Dr)
        # Refund (Cr, if they pay us cash).
        # So Payable Outstanding = (Purchases + Refunds) - (Payments + Returns).
        
        total_paid = payments['total_paid']
        payables_outstanding = (total_purchases + refunds) - (total_paid + total_returns)
        
        return {
            'total_purchases_amount': total_purchases,
            'total_returns': total_returns,
            'total_refunds': refunds,
            'payments': payments,
            'total_paid': total_paid,
            'payables_outstanding': payables_outstanding,
            'payment_percentage': (total_paid / (total_purchases - total_returns) * 100) if (total_purchases - total_returns) > 0 else Decimal('0.00'),
        }
    
    def _get_purchase_payments_breakdown(self) -> Dict[str, Any]:
        """
        Breakdown of how purchase payments were made
        """
        # Get all OUT payments (to vendors) for this business in period
        payments = Payment.objects.filter(
            business=self.business,
            direction=Payment.OUT,
            date__gte=self.start_date,
            date__lte=self.end_date,
            is_deleted=False
        )
        
        # Filter only those applied to Purchase Orders
        # (excluding refunds to customers, etc.)
        po_payment_ids = set(
            payments.filter(
                applied_purchase_orders__isnull=False
            ).values_list('id', flat=True)
        )
        
        po_payments = payments.filter(id__in=po_payment_ids)
        
        # Cash payments
        cash_paid = po_payments.filter(
            payment_method=Payment.PaymentMethod.CASH
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Bank transfer payments
        bank_paid = po_payments.filter(
            payment_method=Payment.PaymentMethod.BANK
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Cheque payments
        cheque_paid = po_payments.filter(
            payment_method=Payment.PaymentMethod.CHEQUE
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        total_paid = cash_paid + bank_paid + cheque_paid
        
        return {
            'cash': cash_paid,
            'bank_transfer': bank_paid,
            'cheque': cheque_paid,
            'total_paid': total_paid,
        }
    
    # ========================================
    # EXPENSES SUMMARY
    # ========================================
    
    def get_expenses_summary(self) -> Dict[str, Any]:
        """
        Complete expenses summary by category and payment method
        """
        expenses = Expense.objects.filter(
            business=self.business,
            date__gte=self.start_date,
            date__lte=self.end_date,
            is_deleted=False
        )
        
        # Total expenses
        total_expenses = expenses.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        
        # By category
        by_category = {}
        for category_code, category_name in Expense.ExpenseCategory.choices:
            amount = expenses.filter(
                category=category_code
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            
            if amount > 0:
                by_category[category_name] = amount
        
        # By payment method
        cash_expenses = expenses.filter(
            payment_source=Expense.CASH
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        bank_expenses = expenses.filter(
            payment_source=Expense.BANK
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        return {
            'total_expenses': total_expenses,
            'by_category': by_category,
            'cash_paid': cash_expenses,
            'bank_paid': bank_expenses,
        }
    
    # ========================================
    # RECEIPTS SUMMARY (already covered in sales)
    # ========================================
    
    def get_receipts_summary(self) -> Dict[str, Any]:
        """
        All receipts (money coming IN) - already detailed in sales
        This is a convenience wrapper
        """
        return self._get_sales_receipts_breakdown()
    
    # ========================================
    # PAYMENTS SUMMARY (already covered in purchases)
    # ========================================
    
    def get_payments_summary(self) -> Dict[str, Any]:
        """
        All payments (money going OUT) - already detailed in purchases
        This is a convenience wrapper
        """
        return self._get_purchase_payments_breakdown()
    
    # ========================================
    # DEPOSITS SUMMARY
    # ========================================
    
    def get_deposits_summary(self) -> Dict[str, Any]:
        """
        Summary of deposits made to bank (cash -> bank, cheque -> bank)
        """
        deposits = BankMovement.objects.filter(
            date__gte=self.start_date,
            date__lte=self.end_date,
            movement_type__in=[BankMovement.DEPOSIT, BankMovement.CHEQUE_DEPOSIT]
        )
        
        # Cash deposits
        cash_deposits = deposits.filter(
            movement_type=BankMovement.DEPOSIT
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Cheque deposits
        cheque_deposits = deposits.filter(
            movement_type=BankMovement.CHEQUE_DEPOSIT
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        total_deposited = cash_deposits + cheque_deposits
        
        # By bank account
        by_bank = {}
        for acc in BankAccount.objects.filter(is_active=True):
            amount = deposits.filter(
                to_bank=acc
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            
            if amount > 0:
                by_bank[acc.name] = amount
        
        return {
            'cash_deposited': cash_deposits,
            'cheque_deposited': cheque_deposits,
            'total_deposited': total_deposited,
            'by_bank_account': by_bank,
        }
    
    # ========================================
    # CURRENT POSITION
    # ========================================
    
    def get_current_position(self) -> Dict[str, Any]:
        """
        Current cash and bank positions (as of end_date)
        """
        # Cash in hand (as of end_date)
        cash_in_hand = self._calculate_cash_balance(before_date=self.end_date, inclusive=True)
        
        # Cheques in hand (pending, not deposited)
        cheques_in_hand = Payment.objects.filter(
            business=self.business,
            direction=Payment.IN,
            payment_method=Payment.PaymentMethod.CHEQUE,
            cheque_status=Payment.ChequeStatus.PENDING,
            date__lte=self.end_date,
            is_deleted=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Bank balances (as of end_date)
        bank_accounts = BankAccount.objects.filter(is_active=True)
        bank_balances = {}
        total_bank = Decimal('0.00')
        
        for acc in bank_accounts:
            balance = self._calculate_bank_balance(acc, before_date=self.end_date, inclusive=True)
            bank_balances[acc.name] = balance
            total_bank += balance
        
        total_liquid = cash_in_hand + total_bank + cheques_in_hand
        
        return {
            'cash_in_hand': cash_in_hand,
            'cheques_in_hand': cheques_in_hand,
            'bank_balances': bank_balances,
            'total_bank': total_bank,
            'total_liquid_assets': total_liquid,
        }
    
    # ========================================
    # CLOSING BALANCE
    # ========================================
    
    def get_closing_balance(self) -> Dict[str, Any]:
        """
        Calculate closing balance
        Opening + Sales - Purchases - Expenses = Closing
        """
        opening = self.get_opening_balance()
        sales = self.get_sales_summary()
        purchases = self.get_purchases_summary()
        expenses = self.get_expenses_summary()
        
        opening_total = opening['total']
        sales_received = sales['total_received']
        purchases_paid = purchases['total_paid']
        expenses_paid = expenses['total_expenses']
        
        # Net cash flow
        net_inflow = sales_received
        net_outflow = purchases_paid + expenses_paid
        net_cash_flow = net_inflow - net_outflow
        
        closing_total = opening_total + net_cash_flow
        
        # Current actual position (should match closing calculated)
        current = self.get_current_position()
        actual_closing = current['total_liquid_assets']
        
        # Difference (if any discrepancy)
        difference = actual_closing - closing_total
        
        return {
            'calculated_closing': closing_total,
            'actual_closing': actual_closing,
            'difference': difference,
            'breakdown': {
                'opening_balance': opening_total,
                'add_sales_received': sales_received,
                'less_purchases_paid': purchases_paid,
                'less_expenses_paid': expenses_paid,
                'net_cash_flow': net_cash_flow,
                'closing_balance': closing_total,
            }
        }
    
    # ========================================
    # HELPER METHODS
    # ========================================
    
    def _calculate_cash_balance(self, before_date: date, inclusive: bool = False) -> Decimal:
        """
        Calculate total cash balance (CashFlow with bank_account=NULL)
        """
        if inclusive:
            flows = CashFlow.objects.filter(date__lte=before_date, bank_account__isnull=True)
        else:
            flows = CashFlow.objects.filter(date__lt=before_date, bank_account__isnull=True)
        
        balance = flows.aggregate(
            net=Sum(
                Case(
                    When(flow_type=CashFlow.IN, then=F('amount')),
                    When(flow_type=CashFlow.OUT, then=-F('amount')),
                    default=Decimal('0.00'),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            )
        )['net'] or Decimal('0.00')
        
        return balance
    
    def _calculate_bank_balance(
        self, 
        bank_account: BankAccount, 
        before_date: date, 
        inclusive: bool = False
    ) -> Decimal:
        """
        Calculate balance for a specific bank account
        """
        if inclusive:
            flows = CashFlow.objects.filter(
                date__lte=before_date,
                bank_account=bank_account
            )
        else:
            flows = CashFlow.objects.filter(
                date__lt=before_date,
                bank_account=bank_account
            )
        
        balance = flows.aggregate(
            net=Sum(
                Case(
                    When(flow_type=CashFlow.IN, then=F('amount')),
                    When(flow_type=CashFlow.OUT, then=-F('amount')),
                    default=Decimal('0.00'),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            )
        )['net'] or Decimal('0.00')
        
        # Add opening balance
        opening = bank_account.opening_balance or Decimal('0.00')
        
        return opening + balance


# ========================================
# QUICK ACCESS FUNCTION
# ========================================

def generate_business_summary_report(
    business: Business,
    start_date: date,
    end_date: date
) -> Dict[str, Any]:
    """
    Quick function to generate business summary report
    
    Usage:
        from barkat.services.business_summary_v2 import generate_business_summary_report
        
        report = generate_business_summary_report(
            business=my_business,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31)
        )
    """
    reporter = BusinessSummaryReportV2(business, start_date, end_date)
    return reporter.generate_full_report()