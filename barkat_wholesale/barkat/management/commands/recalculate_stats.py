from django.core.management.base import BaseCommand
from barkat.models import Party, BankAccount, SummaryStats, Business, BusinessSummary, Product, CashFlow
from barkat.services.balance_service import get_party_balances
from django.db.models import Sum, DecimalField, Case, When, F, Q, ExpressionWrapper, Value
from decimal import Decimal
from django.utils import timezone
from barkat.signals import update_business_summary

class Command(BaseCommand):
    help = 'Recalculates all system totals (SummaryStats, BusinessSummary, Party Balances)'

    def handle(self, *args, **options):
        # 0. Update Business Summaries first
        self.stdout.write("Recalculating BusinessSummaries...")
        for biz in Business.objects.filter(is_deleted=False):
            update_business_summary(biz.id)
            self.stdout.write(f" - Updated {biz.name}")

        # 1. Receivables & Payables (Global)
        self.stdout.write("Calculating global Receivables and Payables...")
        parties = get_party_balances(Party.objects.filter(is_deleted=False))
        total_rec = Decimal("0.00")
        total_pay = Decimal("0.00")
        
        # Also update Party cached_balance
        for p in parties:
            net = p.net_balance or Decimal("0.00")
            if net > 0:
                total_rec += net
            elif net < 0:
                total_pay += abs(net)
            
            # Update cache
            Party.objects.filter(pk=p.id).update(
                cached_balance=net,
                cached_balance_updated_at=timezone.now()
            )
        
        # 2. Cash in Hand (Global)
        self.stdout.write("Calculating global Cash in Hand...")
        
        cash_flows = CashFlow.objects.filter(
            Q(bank_account__isnull=True) | Q(bank_account__account_type=BankAccount.CASH)
        ).aggregate(
            t=Sum(Case(
                When(flow_type=CashFlow.IN, then=F('amount')),
                When(flow_type=CashFlow.OUT, then=-F('amount')),
                default=Decimal('0.00')
            ))
        )['t'] or Decimal('0.00')
        
        cash_acc_opening = BankAccount.objects.filter(
            account_type=BankAccount.CASH,
            is_active=True,
            is_deleted=False
        ).aggregate(s=Sum('opening_balance'))['s'] or Decimal('0.00')
        
        total_cash = cash_flows + cash_acc_opening

        # 3. Total Inventory Valuation (Global)
        self.stdout.write("Calculating global Inventory Valuation...")
        total_valuation = Product.objects.filter(is_deleted=False, is_active=True).aggregate(
            total=Sum(
                ExpressionWrapper(
                    F('purchase_price') * F('stock_qty'),
                    output_field=DecimalField(max_digits=18, decimal_places=2)
                )
            )
        )['total'] or Decimal("0.00")
            
        # 4. Update SummaryStats
        stats = SummaryStats.get_stats()
        stats.total_receivables = max(Decimal("0.00"), total_rec)
        stats.total_payables = max(Decimal("0.00"), total_pay)
        stats.cash_in_hand = total_cash
        stats.total_inventory_valuation = max(Decimal("0.00"), total_valuation)
        stats.save()
        
        self.stdout.write(self.style.SUCCESS(
            f"Recalculation Complete:\n"
            f" - Total Receivables: Rs. {stats.total_receivables:,.2f}\n"
            f" - Total Payables:    Rs. {stats.total_payables:,.2f}\n"
            f" - Cash in Hand:     Rs. {stats.cash_in_hand:,.2f}\n"
            f" - Inventory Value:  Rs. {stats.total_inventory_valuation:,.2f}"
        ))
