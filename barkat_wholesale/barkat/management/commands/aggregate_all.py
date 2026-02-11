from django.core.management.base import BaseCommand
from barkat.models import Business
from barkat.signals import update_business_summary

class Command(BaseCommand):
    help = "Run full initial aggregation for all BusinessSummaries"

    def handle(self, *args, **options):
        businesses = Business.objects.all()
        self.stdout.write(f"Updating summaries for {businesses.count()} businesses...")
        for b in businesses:
            update_business_summary(b.id)
            self.stdout.write(self.style.SUCCESS(f"Successfully updated {b.name}"))
