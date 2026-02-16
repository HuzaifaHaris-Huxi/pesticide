from decimal import Decimal
from django.db.models import Sum, Q, F, Case, When, DecimalField, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import datetime
from barkat.models import (
    SalesOrder, PurchaseOrder, Expense, Payment, 
    BankAccount, CashFlow, SalesOrderReceipt
)

class ReportService:
    @staticmethod
    def get_financial_summary(today=None):
        if not today:
            today = timezone.localdate()
        
        # --- SECTION 1: Performance Headers ---
        sales_qs = SalesOrder.objects.filter(
            business__is_deleted=False,
            is_deleted=False,
            created_at__date=today
        )
        fulfilled_sales = sales_qs.filter(status=SalesOrder.Status.FULFILLED)
        total_sales = fulfilled_sales.aggregate(s=Sum('net_total'))['s'] or Decimal('0.00')
        sales_count = fulfilled_sales.count()
        
        sales_ids = fulfilled_sales.values_list('id', flat=True).order_by('id')
        sales_series = f"SO #{sales_ids[0]} to #{sales_ids[len(sales_ids)-1]}" if sales_ids else "—"
        
        total_receipt = SalesOrderReceipt.objects.filter(
            sales_order__in=fulfilled_sales,
            sales_order__created_at__date=today
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
        
        cancelled_sales = sales_qs.filter(status=SalesOrder.Status.CANCELLED)
        total_cancelled = cancelled_sales.aggregate(s=Sum('net_total'))['s'] or Decimal('0.00')
        cancelled_count = cancelled_sales.count()
        
        po_qs = PurchaseOrder.objects.filter(
            business__is_deleted=False,
            is_deleted=False,
            is_active=True,
            created_at__date=today
        )
        total_purchase = po_qs.aggregate(s=Sum('net_total'))['s'] or Decimal('0.00')
        
        po_ids = po_qs.values_list('id', flat=True).order_by('id')
        po_series = f"PO #{po_ids[0]} to #{po_ids[len(po_ids)-1]}" if po_ids else "—"
        pending_po_count = po_qs.filter(status='pending').count()
        
        expenses_qs = Expense.objects.filter(
            business__is_deleted=False,
            is_deleted=False,
            date=today
        )
        landed_po_expense = expenses_qs.filter(purchase_order__isnull=False).exclude(payment__is_external=True).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
        operating_expense = expenses_qs.filter(purchase_order__isnull=True).exclude(payment__is_external=True).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
        total_expenses = landed_po_expense + operating_expense

        # --- SECTION 2: Amount IN ---
        payments_in = Payment.objects.filter(direction=Payment.IN, date=today, is_deleted=False, is_external=False)
        
        cash_sales = payments_in.filter(
            Q(payment_method=Payment.PaymentMethod.CASH),
            Q(applied_sales_orders__isnull=False) | Q(applied_sales_invoices__isnull=False)
        ).distinct().aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
        
        cash_receipt = payments_in.filter(
            payment_method=Payment.PaymentMethod.CASH,
            applied_sales_orders__isnull=True,
            applied_sales_invoices__isnull=True,
            applied_purchase_returns__isnull=True
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
        
        total_cash_in = cash_sales + cash_receipt
        
        bank_sales = payments_in.filter(
            Q(payment_method__in=[Payment.PaymentMethod.BANK, Payment.PaymentMethod.CARD]),
            Q(applied_sales_orders__isnull=False) | Q(applied_sales_invoices__isnull=False)
        ).distinct().aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
        
        bank_receipt = payments_in.filter(
            payment_method__in=[Payment.PaymentMethod.BANK, Payment.PaymentMethod.CARD],
            applied_sales_orders__isnull=True,
            applied_sales_invoices__isnull=True,
            applied_purchase_returns__isnull=True
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
        
        total_bank_deposits = bank_sales + bank_receipt

        # --- SECTION 3: Amount OUT ---
        payments_out = Payment.objects.filter(direction=Payment.OUT, date=today, is_deleted=False, is_external=False)
        
        po_payments = payments_out.filter(applied_purchase_orders__isnull=False).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
        general_payments = payments_out.filter(
            applied_purchase_orders__isnull=True,
            applied_sales_returns__isnull=True
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
        sr_refunds = payments_out.filter(applied_sales_returns__isnull=False).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
        
        total_cash_out = po_payments + general_payments + sr_refunds + total_expenses

        # --- SECTION 4: Bank Details ---
        bank_accounts = BankAccount.objects.filter(is_active=True, is_deleted=False)
        bank_details = []
        for acc in bank_accounts:
            acc_payments_in = Payment.objects.filter(bank_account=acc, direction=Payment.IN, date=today, is_deleted=False, is_external=False)
            
            bank_sales_amount = acc_payments_in.filter(
                Q(applied_sales_orders__isnull=False) | Q(applied_sales_invoices__isnull=False)
            ).distinct().aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
            
            total_bank_in = CashFlow.objects.filter(
                bank_account=acc, flow_type=CashFlow.IN, date=today, is_deleted=False, linked_payment__isnull=True
            ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
            
            cash_deposited = max(Decimal('0.00'), total_bank_in - bank_sales_amount)
            
            cheque_deposited = Payment.objects.filter(
                bank_account=acc,
                payment_method=Payment.PaymentMethod.CHEQUE,
                cheque_status=Payment.ChequeStatus.DEPOSITED,
                date=today,
                is_deleted=False,
                is_external=False
            ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
            
            total_deposited = bank_sales_amount + cash_deposited + cheque_deposited
            
            total_flow = CashFlow.objects.filter(
                bank_account=acc, date__lte=today, is_deleted=False
            ).aggregate(
                t=Sum(Case(
                    When(flow_type=CashFlow.IN, then=F('amount')),
                    When(flow_type=CashFlow.OUT, then=-F('amount')),
                    default=Decimal('0.00'),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                ))
            )['t'] or Decimal('0.00')
            
            bank_details.append({
                'account': acc,
                'bank_sales_amount': bank_sales_amount,
                'cash_deposited': cash_deposited,
                'cheque_deposited': cheque_deposited,
                'total_deposited': total_deposited,
                'current_balance': acc.opening_balance + total_flow
            })
        
        grand_total_banks = sum(b['current_balance'] for b in bank_details)
        
        # --- SECTION 5: In Hand ---
        cheques_pending = Payment.objects.filter(
            payment_method=Payment.PaymentMethod.CHEQUE,
            cheque_status=Payment.ChequeStatus.PENDING,
            is_deleted=False,
            is_external=False
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')

        return {
            'today': today,
            'total_sales': total_sales,
            'sales_count': sales_count,
            'sales_series': sales_series,
            'total_receipt': total_receipt,
            'total_cancelled': total_cancelled,
            'cancelled_count': cancelled_count,
            'total_purchase': total_purchase,
            'po_series': po_series,
            'pending_po_count': pending_po_count,
            'landed_po_expense': landed_po_expense,
            'operating_expense': operating_expense,
            'total_expenses': total_expenses,
            'cash_sales': cash_sales,
            'cash_receipt': cash_receipt,
            'total_cash_in': total_cash_in,
            'bank_sales': bank_sales,
            'bank_receipt': bank_receipt,
            'total_bank_deposits': total_bank_deposits,
            'po_payments': po_payments,
            'general_payments': general_payments,
            'sr_refunds': sr_refunds,
            'total_cash_out': total_cash_out,
            'bank_details': bank_details,
            'grand_total_banks': grand_total_banks,
            'cash_in_hand': total_cash_in - total_cash_out,
            'cheques_pending': cheques_pending,
            'all_bank_balance': grand_total_banks,
        }
