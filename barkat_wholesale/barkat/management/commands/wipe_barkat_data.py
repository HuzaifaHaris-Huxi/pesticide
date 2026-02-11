from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction
from decimal import Decimal

class Command(BaseCommand):
    help = (
        "Wipe transactional data and clean Master Data:\n"
        "- Deletes ALL Products and Product Categories.\n"
        "- Deletes ALL Businesses EXCEPT ID 1.\n"
        "- Deletes ALL Purchase Orders, Sales Orders, Parties, and Expenses.\n"
        "- Deletes ALL Bank Accounts, Staff, and Warehouses.\n"
        "- Preserves UOMs and Expense Categories."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--noinput",
            action="store_true",
            help="Run without interactive confirmation",
        )

    def handle(self, *args, **options):
        if not options["noinput"]:
            self.stdout.write(self.style.WARNING("!!! DANGER: TOTAL DATA WIPE !!!"))
            self.stdout.write("This will:")
            self.stdout.write("- Delete ALL Products and Product Categories")
            self.stdout.write("- Delete ALL Businesses EXCEPT ID 1")
            self.stdout.write("- Delete ALL Purchase Orders, Sales Orders, Parties, and Expenses")
            self.stdout.write("- Delete ALL Bank Accounts, Staff, and Warehouses")
            self.stdout.write("- Preserve UOMs and Expense Categories")
            
            confirm = input("Type 'yes' to confirm: ").strip().lower()
            if confirm != 'yes':
                self.stdout.write("Aborted.")
                return

        app_label = "barkat"
        
        # Get model classes
        Product = apps.get_model(app_label, "Product")
        ProductCategory = apps.get_model(app_label, "ProductCategory")
        Business = apps.get_model(app_label, "Business")
        PurchaseOrder = apps.get_model(app_label, "PurchaseOrder")
        SalesOrder = apps.get_model(app_label, "SalesOrder")
        Party = apps.get_model(app_label, "Party")
        Expense = apps.get_model(app_label, "Expense")
        BankAccount = apps.get_model(app_label, "BankAccount")
        BankMovement = apps.get_model(app_label, "BankMovement")
        Staff = apps.get_model(app_label, "Staff")
        Warehouse = apps.get_model(app_label, "Warehouse")
        
        # Track models for sequence reset
        wiped_in_order = []
        
        # 1. Delete Purchase Return data
        self.stdout.write(self.style.NOTICE("Deleting Purchase Returns..."))
        try:
            PurchaseReturnItem = apps.get_model(app_label, "PurchaseReturnItem")
            PurchaseReturnRefund = apps.get_model(app_label, "PurchaseReturnRefund")
            PurchaseReturnItem.objects.all().delete()
            PurchaseReturnRefund.objects.all().delete()
            PurchaseReturn = apps.get_model(app_label, "PurchaseReturn")
            PurchaseReturn.objects.all().delete()
            wiped_in_order.extend([PurchaseReturnItem, PurchaseReturnRefund, PurchaseReturn])
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Error deleting purchase returns: {e}"))
        
        # 2. Delete Purchase Order data
        self.stdout.write(self.style.NOTICE("Deleting all Purchase Orders..."))
        try:
            PurchaseOrderItem = apps.get_model(app_label, "PurchaseOrderItem")
            PurchaseOrderPayment = apps.get_model(app_label, "PurchaseOrderPayment")
            PurchaseOrderItem.objects.all().delete()
            PurchaseOrderPayment.objects.all().delete()
            PurchaseOrder.objects.all().delete()
            wiped_in_order.extend([PurchaseOrderItem, PurchaseOrderPayment, PurchaseOrder])
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Error deleting purchase orders: {e}"))
        
        # 3. Delete Sales Return data
        self.stdout.write(self.style.NOTICE("Deleting Sales Returns..."))
        try:
            SalesReturnItem = apps.get_model(app_label, "SalesReturnItem")
            SalesReturnRefund = apps.get_model(app_label, "SalesReturnRefund")
            SalesReturnItem.objects.all().delete()
            SalesReturnRefund.objects.all().delete()
            SalesReturn = apps.get_model(app_label, "SalesReturn")
            SalesReturn.objects.all().delete()
            wiped_in_order.extend([SalesReturnItem, SalesReturnRefund, SalesReturn])
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Error deleting sales returns: {e}"))
        
        # 4. Delete Sales Invoice data
        self.stdout.write(self.style.NOTICE("Deleting Sales Invoices..."))
        try:
            SalesInvoiceItem = apps.get_model(app_label, "SalesInvoiceItem")
            SalesInvoiceReceipt = apps.get_model(app_label, "SalesInvoiceReceipt")
            SalesInvoiceItem.objects.all().delete()
            SalesInvoiceReceipt.objects.all().delete()
            SalesInvoice = apps.get_model(app_label, "SalesInvoice")
            SalesInvoice.objects.all().delete()
            wiped_in_order.extend([SalesInvoiceItem, SalesInvoiceReceipt, SalesInvoice])
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Error deleting sales invoices: {e}"))

        # 5. Delete Sales Order data
        self.stdout.write(self.style.NOTICE("Deleting Sales Orders..."))
        try:
            SalesOrderItem = apps.get_model(app_label, "SalesOrderItem")
            SalesOrderReceipt = apps.get_model(app_label, "SalesOrderReceipt")
            SalesOrderItem.objects.all().delete()
            SalesOrderReceipt.objects.all().delete()
            SalesOrder.objects.all().delete()
            wiped_in_order.extend([SalesOrderItem, SalesOrderReceipt, SalesOrder])
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Error deleting sales orders: {e}"))

        # 6. Delete Products & Categories
        self.stdout.write(self.style.NOTICE("Deleting Products & Categories..."))
        Product.objects.all().delete()
        ProductCategory.objects.all().delete()
        wiped_in_order.extend([Product, ProductCategory])

        # 7. Delete Payments & CashFlows
        self.stdout.write(self.style.NOTICE("Deleting Payments and CashFlows..."))
        try:
            Payment = apps.get_model(app_label, "Payment")
            CashFlow = apps.get_model(app_label, "CashFlow")
            Payment.objects.all().delete()
            CashFlow.objects.all().delete()
            wiped_in_order.extend([Payment, CashFlow])
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Error deleting payments/cashflows: {e}"))

        # 8. Delete Bank Movements FIRST (before Parties - protected FK)
        self.stdout.write(self.style.NOTICE("Deleting Bank Movements..."))
        try:
            BankMovement.objects.all().delete()
            wiped_in_order.append(BankMovement)
            self.stdout.write(self.style.SUCCESS("Deleted all bank movements."))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Error deleting bank movements: {e}"))

        # 9. Delete Expenses, Parties, and Staff
        # Staff must be deleted before Business because of PROTECT constraint
        self.stdout.write(self.style.NOTICE("Deleting Expenses, Staff, and Parties..."))
        Expense.objects.all().delete()
        Staff.objects.all().delete()
        Party.objects.all().delete()
        wiped_in_order.extend([Expense, Staff, Party])

        # 9. Delete Stock and Move records
        self.stdout.write(self.style.NOTICE("Deleting Stock and Warehouse records..."))
        try:
            BusinessStock = apps.get_model(app_label, "BusinessStock")
            WarehouseStock = apps.get_model(app_label, "WarehouseStock")
            StockTransaction = apps.get_model(app_label, "StockTransaction")
            StockMove = apps.get_model(app_label, "StockMove")
            BusinessStock.objects.all().delete()
            WarehouseStock.objects.all().delete()
            StockTransaction.objects.all().delete()
            StockMove.objects.all().delete()
            # Warehouse must be deleted after stocks but before Business
            Warehouse.objects.all().delete()
            wiped_in_order.extend([BusinessStock, WarehouseStock, StockTransaction, StockMove, Warehouse])
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Error deleting stock/warehouses: {e}"))

        # 10. Delete Bank Accounts (BankMovements already deleted above)
        self.stdout.write(self.style.NOTICE("Deleting Bank Accounts..."))
        try:
            bank_count = BankAccount.objects.count()
            BankAccount.objects.all().delete()
            wiped_in_order.append(BankAccount)
            self.stdout.write(self.style.SUCCESS(f"Deleted {bank_count} bank accounts."))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Error deleting bank accounts: {e}"))

        # 11. Delete Businesses except ID 1
        self.stdout.write(self.style.NOTICE("Cleaning Businesses..."))
        Business.objects.exclude(pk=1).delete()

        # 12. Reset Sequences
        self.stdout.write(self.style.NOTICE("Resetting sequences..."))
        with connection.cursor() as cursor:
            vendor = connection.vendor
            for model in wiped_in_order:
                table = model._meta.db_table
                try:
                    if vendor == "sqlite":
                        cursor.execute("DELETE FROM sqlite_sequence WHERE name = ?", [table])
                    elif vendor == "mysql":
                        cursor.execute(f"ALTER TABLE {connection.ops.quote_name(table)} AUTO_INCREMENT = 1")
                    else:
                        sql_list = connection.ops.sequence_reset_sql(no_style(), [model])
                        for sql in sql_list: cursor.execute(sql)
                except: pass

        # 13. Recalculate all summary statistics to reset cached balances
        self.stdout.write(self.style.NOTICE("Recalculating summary statistics to zero out cached balances..."))
        from django.core.management import call_command
        try:
            call_command('recalculate_stats')
            self.stdout.write(self.style.SUCCESS("Summary stats recalculated."))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Error recalculating stats: {e}"))

        self.stdout.write(self.style.SUCCESS("Database wiped successfully!"))