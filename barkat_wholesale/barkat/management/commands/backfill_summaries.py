from django.core.management.base import BaseCommand
from barkat.models import Business
from barkat.signals import update_business_summary

class Command(BaseCommand):
    help = 'Backfills BusinessSummary for all businesses'

    def handle(self, *args, **options):
        businesses = Business.objects.all()
        for biz in businesses:
            self.stdout.write(f"Updating summary for {biz.name}...")
            update_business_summary(biz.id)
        self.stdout.write(self.style.SUCCESS('Successfully updated all business summaries'))
