# barkat/management/commands/list_printers.py
from django.core.management.base import BaseCommand
try:
    import win32print
except Exception:
    win32print = None

class Command(BaseCommand):
    help = "List installed Windows printers"

    def handle(self, *args, **opts):
        if not win32print:
            self.stderr.write("pywin32 not installed or not on Windows.")
            return
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        for p in win32print.EnumPrinters(flags):
            self.stdout.write(p[2])
