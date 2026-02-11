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

        # 1. Unified Global Financials
        self.stdout.write("Calculating global financial metrics...")
        from barkat.services.financial_logic import get_business_financials
        global_stats = get_business_financials()

        # 2. Update Party cached_balance (Maintenance)
        self.stdout.write("Updating party cached balances...")
        parties = get_party_balances(Party.objects.filter(is_deleted=False))
        for p in parties:
            net = p.net_balance or Decimal("0.00")
            Party.objects.filter(pk=p.id).update(
                cached_balance=net,
                cached_balance_updated_at=timezone.now()
            )
            
        # 3. Update SummaryStats (Singleton)
        stats = SummaryStats.get_stats()
        stats.total_receivables = global_stats["total_receivables"]
        stats.total_payables = global_stats["total_payables"]
        stats.cash_in_hand = global_stats["cash_in_hand"]
        stats.total_inventory_valuation = global_stats["inventory_value"]
        stats.save()
        
        self.stdout.write(self.style.SUCCESS(
            f"Recalculation Complete:\n"
            f" - Total Receivables: Rs. {stats.total_receivables:,.2f}\n"
            f" - Total Payables:    Rs. {stats.total_payables:,.2f}\n"
            f" - Cash in Hand:     Rs. {stats.cash_in_hand:,.2f}\n"
            f" - Inventory Value:  Rs. {stats.total_inventory_valuation:,.2f}"
        ))
