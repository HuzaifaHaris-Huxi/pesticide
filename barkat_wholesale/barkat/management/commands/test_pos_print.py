# barkat/management/commands/test_pos_print.py
from django.core.management.base import BaseCommand, CommandError
from barkat.models import Business
from barkat.utils.receipt_render import render_receipt_bitmap
from barkat.utils.pos_print import raw_print_bitmap, PosPrintError

class Command(BaseCommand):
    help = "Send a tiny test slip to the configured POS printer"

    def add_arguments(self, parser):
        parser.add_argument("--business", type=int, required=True)
        parser.add_argument("--width", type=int, default=576)

    def handle(self, *args, **opts):
        b = Business.objects.filter(pk=opts["business"]).first()
        if not b or not b.pos_printer_name:
            raise CommandError("Business not found or no pos_printer_name set.")
        # Render a tiny slip
        class Dummy: pass
        order = Dummy(); order.id = 0; order.tax_percent = 0; order.discount_percent = 0
        items = []
        path = render_receipt_bitmap(business=b, order=order, items=items, width_px=opts["width"], out_dir=".")
        try:
            raw_print_bitmap(b.pos_printer_name, path, width_px=opts["width"])
        except PosPrintError as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(f"Printed test to {b.pos_printer_name}"))
