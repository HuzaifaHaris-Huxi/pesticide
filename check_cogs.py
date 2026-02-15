import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pesticide.settings')
django.setup()

from barkat.models import SalesOrderItem, Product

print("Checking Award 1kg sales items:")
p = Product.objects.filter(name__icontains="Award 1kg").first()
if p:
    items = SalesOrderItem.objects.filter(product=p)
    print(f"Product: {p.name}, Current Purchase Price: {p.purchase_price}")
    for item in items:
        print(f"  Item ID: {item.id}, Qty: {item.quantity}, Unit Price: {item.unit_price}, Snapshot Unit Cost: {item.unit_cost}, Subtotal Cost: {item.quantity * item.unit_cost}")
else:
    print("Award 1kg not found.")

print("\nSummary check:")
items_all = SalesOrderItem.objects.all()
zero_cost_items = items_all.filter(unit_cost=0, quantity__gt=0)
print(f"Total SalesOrderItems: {items_all.count()}")
print(f"Total Items with Zero Unit Cost: {zero_cost_items.count()}")
for item in zero_cost_items[:10]:
    print(f"  Zero Cost Item: {item.product.name}, Qty: {item.quantity}")
