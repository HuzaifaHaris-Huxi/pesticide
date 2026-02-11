import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'barkat_wholesale.settings')
django.setup()

from barkat.utils.receipt_render import test_urdu_rendering

# Run diagnostic test
test_urdu_rendering()