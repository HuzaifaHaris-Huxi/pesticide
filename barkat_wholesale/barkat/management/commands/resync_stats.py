from django.core.management.base import BaseCommand
from barkat.services.stats_service import recompute_summary_stats

class Command(BaseCommand):
    help = 'Recomputes the global SummaryStats from source records to ensure data consistency.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Starting SummaryStats recomputation...'))
        
        try:
            stats = recompute_summary_stats()
            self.stdout.write(self.style.SUCCESS('Successfully recomputed SummaryStats!'))
            self.stdout.write(f"Receivables: {stats.total_receivables}")
            self.stdout.write(f"Payables:    {stats.total_payables}")
            self.stdout.write(f"Cash:        {stats.cash_in_hand}")
            self.stdout.write(f"Inventory:   {stats.total_inventory_valuation}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error during recomputation: {str(e)}"))
