import os
import django
import sys

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'barkat_wholesale.settings')
django.setup()

from django.conf import settings
from django.utils import timezone
import datetime

print("===== DJANGO SETTINGS =====")
print(f"TIME_ZONE: {settings.TIME_ZONE}")
print(f"USE_TZ: {settings.USE_TZ}")

print("\n===== TIMEZONE TEST =====")
now = timezone.now()
print(f"1. UTC time: {now}")
print(f"2. Timezone: {now.tzinfo}")

# Try manual conversion with pytz
try:
    import pytz
    print(f"\n3. pytz version: {pytz.__version__}")
    pak_tz = pytz.timezone('Asia/Karachi')
    pak_time = now.astimezone(pak_tz)
    print(f"4. Manual Pakistan time: {pak_time}")
    print(f"5. Timezone: {pak_time.tzinfo}")
    
    # Make naive
    naive_pak = pak_time.replace(tzinfo=None)
    formatted = naive_pak.strftime('%Y-%m-%dT%H:%M')
    print(f"6. Formatted for input: {formatted}")
    print(f"\n✅ THIS SHOULD SHOW 21:22, NOT 16:22")
except Exception as e:
    print(f"Error: {e}")

# Try Django's localtime
print("\n===== DJANGO LOCALTIME =====")
local = timezone.localtime(now)
print(f"7. Django localtime: {local}")
print(f"8. Timezone: {local.tzinfo}")
