from django.core.management.base import BaseCommand
from barkat.models import Party
from barkat.services.balance_service import get_party_balances
from django.utils import timezone
from decimal import Decimal

class Command(BaseCommand):
    help = 'Recalculates and caches balances for all parties'

    def handle(self, *args, **options):
        self.stdout.write("Fetching all parties...")
        qs = Party.objects.all()
        
        self.stdout.write("Calculating balances using subqueries...")
        # This executes the unified balance logic for ALL parties in one go (or paged internally by DB)
        qs = get_party_balances(qs)
        
        objs_to_update = []
        now = timezone.now()
        count = 0
        
        # Determine total for progress bar (optional)
        # Using iterator to be memory efficient if large, but we need list for bulk_update.
        # If huge, we should chunk. Assuming < 10,000 parties, list is fine.
        
        for party in qs:
            net = party.net_balance or Decimal("0.00")
            party.cached_balance = net
            party.cached_balance_updated_at = now
            objs_to_update.append(party)
            count += 1
            
        if objs_to_update:
            self.stdout.write(f"Updating {len(objs_to_update)} parties...")
            # Chunked bulk_update for safety
            batch_size = 500
            for i in range(0, len(objs_to_update), batch_size):
                batch = objs_to_update[i:i+batch_size]
                Party.objects.bulk_update(batch, ['cached_balance', 'cached_balance_updated_at'])
                self.stdout.write(f"Updated {min(i+batch_size, len(objs_to_update))}/{len(objs_to_update)}")
                
        self.stdout.write(self.style.SUCCESS(f'Successfully updated cached balances for {count} parties.'))
