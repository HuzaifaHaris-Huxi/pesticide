import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'barkat_wholesale.settings')
django.setup()

from barkat.models import SalesOrderItem

def backfill_item_costs():
    items = SalesOrderItem.objects.filter(Q(unit_cost__isnull=True) | Q(unit_cost=Decimal("0.00")))
    count = items.count()
    print(f"Filtering {count} items for cost backfill...")
    
    updated = 0
    for it in items:
        it.unit_cost = it.product.purchase_price or Decimal("0.00")
        it.save(update_fields=['unit_cost'])
        updated += 1
        if updated % 100 == 0:
            print(f"Updated {updated}/{count}...")
            
    print(f"Successfully backfilled costs for {updated} items.")

if __name__ == "__main__":
    from django.db.models import Q
    backfill_item_costs()
