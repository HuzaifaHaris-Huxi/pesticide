import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'barkat_wholesale.settings')
django.setup()

from django.contrib.auth import get_user_model
from barkat.models import Business, Product, PurchaseOrder, PurchaseOrderItem, Expense, SalesOrder, SalesOrderItem, Party, UnitOfMeasure, ExpenseCategory

User = get_user_model()

def verify_all():
    print("--- Starting Verification ---")
    
    # 1. Setup Data
    user = User.objects.first()
    if not user:
        user = User.objects.create_superuser('testuser', 'test@example.com', 'password123')
        print(f"✅ Created Superuser: {user.username}")
    else:
        print(f"✅ Found User: {user.username}")

    biz = Business.objects.first()
    if not biz:
        print("❌ No business found")
        return
    
    # Party uses 'type' field and 'default_business'
    supplier = Party.objects.filter(type=Party.VENDOR).first()
    if not supplier:
        supplier = Party.objects.create(display_name="Test Supplier V5", type=Party.VENDOR, default_business=biz, created_by=user, updated_by=user)
        
    customer = Party.objects.filter(type=Party.CUSTOMER).first()
    if not customer:
        customer = Party.objects.create(display_name="Test Customer V5", type=Party.CUSTOMER, default_business=biz, created_by=user, updated_by=user)

    uom_kg = UnitOfMeasure.objects.filter(code__iexact='kg').first() or UnitOfMeasure.objects.first()
    
    prod = Product.objects.create(
        business=biz,
        name="Verification Product V5-F",
        purchase_price=Decimal("100.00"),
        sale_price=Decimal("150.00"),
        uom=uom_kg,
        created_by=user,
        updated_by=user
    )
    print(f"✅ Created Product: {prod.name}")

    # 2. Verify Landed Cost Automation
    po = PurchaseOrder.objects.create(
        business=biz,
        supplier=supplier,
        status="received",
        created_by=user,
        updated_by=user
    )
    
    item = PurchaseOrderItem.objects.create(
        purchase_order=po,
        product=prod,
        quantity=Decimal("10.00"),
        unit_price=Decimal("100.00"),
        size_per_unit=Decimal("1.000000"),
        uom=uom_kg
    )
    
    # Refresh item from DB
    item.refresh_from_db()
    print(f"📊 Initial Item Landing Price: {item.landing_unit_price}")
    
    # Add an expense that should be distributed
    exp = Expense.objects.create(
        business=biz,
        purchase_order=po,
        category='freight',
        amount=Decimal("50.00"),
        divide_per_unit=True,
        created_by=user,
        updated_by=user
    )
    
    # Refresh item from DB
    item.refresh_from_db()
    print(f"📊 After Expense Landing Price: {item.landing_unit_price} (Expected 105.00)")
    
    if item.landing_unit_price != Decimal("105.00"):
        print(f"❌ Landed cost distribution failed! Found {item.landing_unit_price}")
    else:
        print("✅ Landed cost distribution auto-triggered successfully")

    # 3. Verify Sales Snapshotting
    prod.purchase_price = item.landing_unit_price
    prod.save()
    
    so = SalesOrder.objects.create(
        business=biz,
        customer=customer,
        created_by=user,
        updated_by=user
    )
    
    so_item = SalesOrderItem.objects.create(
        sales_order=so,
        product=prod,
        quantity=Decimal("2.00"),
        unit_price=Decimal("200.00")
    )
    
    print(f"📊 Sales snapshot unit_cost: {so_item.unit_cost} (Expected 105.00)")
    
    if so_item.unit_cost != Decimal("105.00"):
        print(f"❌ Sales snapshotting failed! Found {so_item.unit_cost}")
    else:
        print("✅ Sales snapshotting successful")

    # 4. Clean up
    so_item.delete()
    so.delete()
    exp.delete()
    item.delete()
    po.delete()
    print("--- Verification Finished ---")

if __name__ == "__main__":
    verify_all()
