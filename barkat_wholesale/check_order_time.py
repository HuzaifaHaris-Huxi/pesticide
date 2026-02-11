import os
import django
import sys

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'barkat_wholesale.settings')
django.setup()

from django.conf import settings
from barkat.models import SalesOrder

print("===== CHECKING SALES ORDERS =====")
print(f"TIME_ZONE setting: {settings.TIME_ZONE}")
print(f"USE_TZ setting: {settings.USE_TZ}")

# Get the most recent sales order
try:
    latest_order = SalesOrder.objects.latest('created_at')
    print(f"\nLatest Order ID: {latest_order.id}")
    print(f"Created At (raw from DB): {latest_order.created_at}")
    print(f"Timezone info: {latest_order.created_at.tzinfo}")
    
    from django.utils import timezone
    local_time = timezone.localtime(latest_order.created_at)
    print(f"Converted to local: {local_time}")
    print(f"Local timezone: {local_time.tzinfo}")
    
    naive = local_time.replace(tzinfo=None)
    print(f"Naive for form: {naive}")
    print(f"Formatted: {naive.strftime('%Y-%m-%d %H:%M')}")
except Exception as e:
    print(f"Error: {e}")
