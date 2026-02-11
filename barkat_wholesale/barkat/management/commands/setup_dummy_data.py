from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
from django.contrib.auth import get_user_model
from barkat.models import (
    Business, Staff, UnitOfMeasure, Product, ProductCategory, 
    Party, BankAccount, Warehouse, PurchaseOrder, PurchaseOrderItem, 
    Expense, ExpenseCategory
)

User = get_user_model()

class Command(BaseCommand):
    help = 'Generates dummy data for testing the ERP system'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Starting dummy data generation...")

        # 1. Create Business
        biz, _ = Business.objects.get_or_create(
            code="B001",
            defaults={"name": "Barkat Main Hub", "legal_name": "Barkat Trading Co."}
        )

        # 2. Create Staff User
        admin_user, created = User.objects.get_or_create(username="admin_staff")
        if created:
            admin_user.set_password("admin123")
            admin_user.save()

        # 3. Units & Master Data
        kg, _ = UnitOfMeasure.objects.get_or_create(code="KG")
        bag, _ = UnitOfMeasure.objects.get_or_create(code="BAG")
        cat, _ = ProductCategory.objects.get_or_create(business=biz, name="Grains")
        supplier, _ = Party.objects.get_or_create(display_name="Mill Supplier", type=Party.BOTH)

        # 4. Product with Bulk Settings
        sugar, _ = Product.objects.get_or_create(
            business=biz,
            name="Premium Sugar",
            defaults={
                "category": cat,
                "uom": kg,
                "bulk_uom": bag,
                "default_bulk_size": Decimal("50.00"),
                "purchase_price": Decimal("100.00")
            }
        )

        # 5. Purchase Order + Expense (The Cost Distribution Test)
        po = PurchaseOrder.objects.create(
            business=biz, supplier=supplier, created_by=admin_user, updated_by=admin_user
        )
        
        item = PurchaseOrderItem.objects.create(
            purchase_order=po, product=sugar, uom=bag, 
            quantity=Decimal("10"), unit_price=Decimal("5000.00")
        )

        # Create linked expense to test 'divide_per_unit' distribution
        Expense.objects.create(
            business=biz, 
            purchase_order=po, 
            # Ensure this matches the uppercase variable name in your ExpenseCategory class
            category=ExpenseCategory.FREIGHT, 
            amount=Decimal("1000.00"), 
            divide_per_unit=True, # This triggers the landing cost math in your model
            created_by=admin_user, 
            updated_by=admin_user
        )   
        self.stdout.write(self.style.SUCCESS('Successfully created dummy data and tested landing cost distribution.'))