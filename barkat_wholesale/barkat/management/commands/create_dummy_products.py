# barkat/management/commands/create_dummy_products.py

from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
import random

from barkat.models import Product, Business, ProductCategory, UnitOfMeasure


class Command(BaseCommand):
    help = "Create at least 200 dummy products with realistic data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=200,
            help="Number of products to create (default: 200)",
        )
        parser.add_argument(
            "--noinput",
            action="store_true",
            help="Run without interactive confirmation",
        )

    def handle(self, *args, **options):
        count = options["count"]
        
        if not options["noinput"]:
            self.stdout.write(self.style.WARNING(f"This will create {count} dummy products."))
            confirm = input("Type 'yes' to continue: ").strip().lower()
            if confirm != 'yes':
                self.stdout.write("Aborted.")
                return

        # Get available businesses
        businesses = Business.objects.filter(is_deleted=False, is_active=True)
        if not businesses.exists():
            self.stdout.write(self.style.ERROR("No active businesses found. Please create a business first."))
            return

        # Get available UOMs
        uoms = UnitOfMeasure.objects.all()
        if not uoms.exists():
            self.stdout.write(self.style.ERROR("No UOMs found. Please create UOMs first."))
            return

        # Product data templates
        product_templates = [
            # Food & Beverages
            {"name": "Potato Chips", "company": "Lays", "category": "Snacks", "purchase": (10, 50), "sale": (15, 70)},
            {"name": "Coca Cola", "company": "Coca-Cola", "category": "Beverages", "purchase": (15, 40), "sale": (25, 60)},
            {"name": "Pepsi", "company": "PepsiCo", "category": "Beverages", "purchase": (15, 40), "sale": (25, 60)},
            {"name": "Biscuits", "company": "Oreo", "category": "Snacks", "purchase": (20, 80), "sale": (30, 120)},
            {"name": "Chocolate", "company": "Cadbury", "category": "Confectionery", "purchase": (25, 150), "sale": (40, 200)},
            {"name": "Rice", "company": "Basmati", "category": "Grains", "purchase": (50, 200), "sale": (80, 300)},
            {"name": "Wheat Flour", "company": "Fresh", "category": "Grains", "purchase": (40, 150), "sale": (60, 200)},
            {"name": "Cooking Oil", "company": "Sunflower", "category": "Cooking", "purchase": (100, 300), "sale": (150, 400)},
            {"name": "Salt", "company": "Iodized", "category": "Spices", "purchase": (10, 30), "sale": (15, 50)},
            {"name": "Sugar", "company": "White", "category": "Sweeteners", "purchase": (40, 100), "sale": (60, 150)},
            
            # Personal Care
            {"name": "Soap", "company": "Lux", "category": "Personal Care", "purchase": (15, 80), "sale": (25, 120)},
            {"name": "Shampoo", "company": "Pantene", "category": "Personal Care", "purchase": (80, 300), "sale": (120, 450)},
            {"name": "Toothpaste", "company": "Colgate", "category": "Personal Care", "purchase": (50, 150), "sale": (80, 200)},
            {"name": "Toothbrush", "company": "Oral-B", "category": "Personal Care", "purchase": (30, 100), "sale": (50, 150)},
            {"name": "Face Cream", "company": "Nivea", "category": "Personal Care", "purchase": (100, 400), "sale": (150, 600)},
            
            # Cleaning Supplies
            {"name": "Detergent", "company": "Surf", "category": "Cleaning", "purchase": (80, 200), "sale": (120, 300)},
            {"name": "Dish Soap", "company": "Vim", "category": "Cleaning", "purchase": (40, 100), "sale": (60, 150)},
            {"name": "Floor Cleaner", "company": "Harpic", "category": "Cleaning", "purchase": (60, 150), "sale": (90, 220)},
            {"name": "Toilet Paper", "company": "Soft", "category": "Cleaning", "purchase": (100, 300), "sale": (150, 450)},
            
            # Electronics
            {"name": "USB Cable", "company": "TechPro", "category": "Electronics", "purchase": (50, 200), "sale": (100, 350)},
            {"name": "Phone Charger", "company": "FastCharge", "category": "Electronics", "purchase": (100, 300), "sale": (150, 450)},
            {"name": "Earbuds", "company": "SoundMax", "category": "Electronics", "purchase": (200, 800), "sale": (300, 1200)},
            {"name": "Power Bank", "company": "PowerUp", "category": "Electronics", "purchase": (500, 1500), "sale": (800, 2000)},
            
            # Stationery
            {"name": "Pen", "company": "Bic", "category": "Stationery", "purchase": (5, 30), "sale": (10, 50)},
            {"name": "Notebook", "company": "Classic", "category": "Stationery", "purchase": (50, 200), "sale": (80, 300)},
            {"name": "Pencil", "company": "HB", "category": "Stationery", "purchase": (3, 20), "sale": (5, 30)},
            {"name": "Eraser", "company": "Soft", "category": "Stationery", "purchase": (5, 25), "sale": (10, 40)},
            
            # Clothing
            {"name": "T-Shirt", "company": "Cotton", "category": "Clothing", "purchase": (200, 800), "sale": (300, 1200)},
            {"name": "Jeans", "company": "Denim", "category": "Clothing", "purchase": (500, 2000), "sale": (800, 3000)},
            {"name": "Socks", "company": "Comfort", "category": "Clothing", "purchase": (50, 200), "sale": (80, 300)},
        ]

        # Variants and sizes
        variants = ["Small", "Medium", "Large", "XL", "500g", "1kg", "2kg", "5kg", "250ml", "500ml", "1L", "2L", "Regular", "Family Pack", "Jumbo"]
        flavors = ["Original", "Masala", "Cheese", "Tangy", "Spicy", "Sweet", "Salted", "Unsalted", "Vanilla", "Chocolate"]

        created_count = 0
        
        with transaction.atomic():
            # Create categories for each business if they don't exist
            categories_by_business = {}
            for business in businesses:
                categories_by_business[business] = {}
                for template in product_templates:
                    cat_name = template["category"]
                    if cat_name not in categories_by_business[business]:
                        category, _ = ProductCategory.objects.get_or_create(
                            business=business,
                            name=cat_name,
                            defaults={"code": cat_name[:10].upper().replace(" ", "")}
                        )
                        categories_by_business[business][cat_name] = category

            # Generate products
            self.stdout.write(self.style.NOTICE(f"Creating {count} products..."))
            
            for i in range(count):
                # Select random business
                business = random.choice(businesses)
                
                # Select random template
                template = random.choice(product_templates)
                
                # Create product name with variant/flavor
                if random.choice([True, False]):
                    variant = random.choice(variants)
                    product_name = f"{template['name']} {variant}"
                else:
                    flavor = random.choice(flavors)
                    product_name = f"{template['name']} {flavor}"
                
                # Get or use random category
                category = categories_by_business[business].get(template["category"])
                
                # Generate SKU
                sku = f"SKU{random.randint(10000, 99999)}"
                # Ensure SKU is unique for this business
                while Product.objects.filter(business=business, sku=sku).exists():
                    sku = f"SKU{random.randint(10000, 99999)}"
                
                # Generate barcode using the model method
                barcode = Product.generate_barcode(business=business)
                
                # Random UOM
                uom = random.choice(uoms)
                
                # Random prices
                purchase_min, purchase_max = template["purchase"]
                sale_min, sale_max = template["sale"]
                purchase_price = Decimal(str(random.randint(purchase_min, purchase_max)))
                sale_price = Decimal(str(random.randint(sale_min, sale_max)))
                # Ensure sale price is higher than purchase price
                if sale_price <= purchase_price:
                    sale_price = purchase_price + Decimal("10")
                
                # Random stock quantity
                stock_qty = Decimal(str(random.randint(0, 500)))
                min_stock = Decimal(str(random.randint(10, 100)))
                
                # Random flags
                is_serialized = random.choice([True, False])
                has_expiry = random.choice([True, False])
                
                # Create product
                product = Product.objects.create(
                    business=business,
                    category=category,
                    name=product_name,
                    company_name=template["company"],
                    sku=sku,
                    barcode=barcode,
                    uom=uom,
                    purchase_price=purchase_price,
                    sale_price=sale_price,
                    min_stock=min_stock,
                    stock_qty=stock_qty,
                    is_serialized=is_serialized,
                    has_expiry=has_expiry,
                )
                
                created_count += 1
                
                if created_count % 50 == 0:
                    self.stdout.write(f"Created {created_count} products...")

        self.stdout.write(self.style.SUCCESS(f"Successfully created {created_count} dummy products!"))
        self.stdout.write(f"Businesses used: {businesses.count()}")
        self.stdout.write(f"Categories created: {sum(len(cats) for cats in categories_by_business.values())}")
