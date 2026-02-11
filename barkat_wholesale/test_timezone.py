import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'barkat_wholesale.settings')
django.setup()

from django.utils import timezone
import datetime

# Test timezone conversion
now = timezone.now()
print(f"1. Current UTC time: {now}")
print(f"2. Timezone aware? {timezone.is_aware(now)}")

local = timezone.localtime(now)
print(f"3. Local Pakistan time: {local}")
print(f"4. Timezone aware? {timezone.is_aware(local)}")

# Make naive for datetime-local input
naive = local.replace(tzinfo=None)
print(f"5. Naive local time: {naive}")
print(f"6. Timezone aware? {timezone.is_aware(naive)}")

# Format for datetime-local
formatted = naive.strftime('%Y-%m-%dT%H:%M')
print(f"7. Formatted for input: {formatted}")

print("\n===== EXPECTED =====")
print("Step 7 should show 21:18 (9:18 PM), NOT 16:18 (4:18 PM)")

