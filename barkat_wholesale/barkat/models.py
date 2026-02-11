# barkat/models.py
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import datetime
from django.db.models import UniqueConstraint
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum, F, Case, When, DecimalField, Q

# --------------------------------
# Common field presets
# --------------------------------
DECIMAL_12_2 = {"max_digits": 12, "decimal_places": 2}
DECIMAL_18_6 = {"max_digits": 18, "decimal_places": 6}  # qty, rates, conversions


# --------------------------------
# Core mixins
# --------------------------------
class TimeStampedBy(models.Model):
    created_at = models.DateTimeField(default=timezone.now, db_index=True, editable=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="%(class)s_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="%(class)s_updated"
    )
    is_active = models.BooleanField(default=True, db_index=True)
    is_deleted = models.BooleanField(default=False, db_index=True)

    class Meta:
        abstract = True


class CodeNamed(TimeStampedBy):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, db_index=True)

    class Meta:
        abstract = True


# --------------------------------
# Multi-business structure
# --------------------------------
class Business(CodeNamed):
    """
    Each 'Business' is one independent unit with its own catalogs, stock, and billings.
    Parties/banks/staff can still be shared where desired.
    """
    legal_name = models.CharField(max_length=255, blank=True, default="")
    ntn = models.CharField(max_length=50, blank=True, default="")        # Pakistan context
    sales_tax_reg = models.CharField(max_length=50, blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    address = models.TextField(blank=True, default="")

    pos_printer_name = models.CharField(
        max_length=200, blank=True,
        help_text="POS80 Printer"
    )
    class Meta:
        unique_together = [("code",)]
        indexes = [models.Index(fields=["name"]), models.Index(fields=["code"])]

    def __str__(self):
        return f"{self.code} — {self.name}"


class BusinessSummary(models.Model):
    """
    High-performance aggregation table for dashboard metrics.
    Updated via signals on Sales, Purchases, Payments, and Expenses.
    """
    business = models.OneToOneField(Business, on_delete=models.CASCADE, related_name="summary")
    total_receivables = models.DecimalField(**DECIMAL_12_2, default=Decimal("0.00"))
    total_payables = models.DecimalField(**DECIMAL_12_2, default=Decimal("0.00"))
    cash_in_hand = models.DecimalField(**DECIMAL_12_2, default=Decimal("0.00"))
    bank_balance = models.DecimalField(**DECIMAL_12_2, default=Decimal("0.00"))
    inventory_value = models.DecimalField(**DECIMAL_12_2, default=Decimal("0.00"))
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Business Summaries"

    def __str__(self):
        return f"Summary: {self.business.name}"

    @property
    def net_worth(self):
        """Total Liquid Assets + Inventory - Payables"""
        return (self.cash_in_hand + self.bank_balance + self.inventory_value + self.total_receivables) - self.total_payables


class SummaryStats(models.Model):
    """
    Singleton-like table for global financial health metrics.
    Updated via F() expressions in signals.
    """
    total_receivables = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total_payables    = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    cash_in_hand      = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total_inventory_valuation = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    last_updated      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Summary Stats"

    def __str__(self):
        return f"Global Stats: R={self.total_receivables}, P={self.total_payables}, C={self.cash_in_hand}"

    @classmethod
    def get_stats(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

# --------------------------------
# Master data (shared or per business)
# --------------------------------
class Party(TimeStampedBy):
    """
    A single entity for both Customers and Vendors (Parties).
    Use type to categorize. This allows shared ledgers and payments.
    """
    CUSTOMER = "CUSTOMER"
    VENDOR = "VENDOR"
    BOTH = "BOTH"
    PARTY_TYPES = [(CUSTOMER, "Customer"), (VENDOR, "Vendor"), (BOTH, "Both")]

    type = models.CharField(max_length=20, choices=PARTY_TYPES, db_index=True)
    display_name = models.CharField(max_length=255, db_index=True)
    legal_name = models.CharField(max_length=255, blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    address = models.TextField(blank=True, default="")
    gst_number = models.CharField(max_length=50, blank=True, default="")
    opening_balance = models.DecimalField(**DECIMAL_12_2, default=0)
    opening_balance_side = models.CharField(
        max_length=2,
        choices=[('Dr', 'Debit (They owe us)'), ('Cr', 'Credit (We owe them)')],
        default='Dr',
        help_text='Specify whether the opening balance is Debit or Credit'
    )
    opening_balance_date = models.DateField(
        null=True,
        blank=True,
        help_text='Date when the opening balance was set (defaults to party creation date)'
    )
    
    # Optimization: Signal-updated cached balance
    cached_balance = models.DecimalField(**DECIMAL_12_2, default=0, editable=False)
    cached_balance_updated_at = models.DateTimeField(null=True, blank=True, editable=False)

    # Optional default business for price lists or terms; parties remain shareable
    default_business = models.ForeignKey(Business, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        indexes = [models.Index(fields=["type", "display_name"])]

    def __str__(self):
        return self.display_name

class UnitOfMeasure(CodeNamed):
    """
    Base UOM; conversions allow KG<->G, CTN<->PCS etc.
    """
    symbol = models.CharField(max_length=20, blank=True, default="")

    class Meta:
        unique_together = [("code",)]
        indexes = [models.Index(fields=["code"])]

    def __str__(self):
        return self.code

class UOMConversion(TimeStampedBy):
    from_uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="conversions_from")
    to_uom   = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="conversions_to")
    factor   = models.DecimalField(**DECIMAL_18_6, validators=[MinValueValidator(0.000001)])  # multiply by factor to go FROM -> TO

    class Meta:
        unique_together = [("from_uom", "to_uom")]

    def __str__(self):
        return f"1 {self.from_uom.code} = {self.factor} {self.to_uom.code}"

class ProductCategory(TimeStampedBy):
    business = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="product_categories")
    name = models.CharField(max_length=255, db_index=True)
    code = models.CharField(max_length=50, db_index=True, null=True, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")

    class Meta:
        unique_together = [("business", "code")]
        indexes = [models.Index(fields=["business", "code"]), models.Index(fields=["business", "name"])]

    def __str__(self):
        code_part = self.code if self.code else "NO-CODE"
        return f"{self.business.code}/{code_part}"

class Product(TimeStampedBy):
    business = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="products")
    category = models.ForeignKey(ProductCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="products")
    name = models.CharField(max_length=255, db_index=True)
    company_name = models.CharField(max_length=255, blank=True, default="", db_index=True, help_text="Brand/Company name (e.g., Lays, Coca-Cola)")
    sku = models.CharField(max_length=100, db_index=True, null=True, blank=True)
    barcode = models.CharField(max_length=100, blank=True, default="", db_index=True)
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="products")
    purchase_price = models.DecimalField(**DECIMAL_12_2, default=0)
    sale_price = models.DecimalField(**DECIMAL_12_2, default=0)
    min_stock = models.DecimalField(**DECIMAL_18_6, default=0)
    stock_qty = models.DecimalField(**DECIMAL_18_6, default=Decimal("0"))
    is_serialized = models.BooleanField(default=False)
    has_expiry = models.BooleanField(default=False)

    # NEW: Default bulk settings
    bulk_uom = models.ForeignKey(
        UnitOfMeasure, null=True, blank=True, 
        on_delete=models.SET_NULL, related_name="bulk_products"
    ) # e.g., "Bag"
    default_bulk_size = models.DecimalField(
        **DECIMAL_18_6, default=Decimal("1.000000"),
        help_text="Standard weight/qty per Bulk Unit (e.g., 50.00)"
    )
    
    class Meta:
        unique_together = [("business", "sku")]
        indexes = [
            models.Index(fields=["business", "sku"]),
            models.Index(fields=["business", "name"]),
            models.Index(fields=["barcode"]),
            models.Index(fields=["company_name"]),
            models.Index(fields=["business", "company_name"]),
        ]

    @staticmethod
    def generate_barcode(business=None, product_id=None):
        """
        Generate a unique barcode for a product.
        Format: AL{8-digit-number}
        Always starts with "AL" prefix followed by numeric digits.
        Checks entire database to ensure uniqueness.
        """
        import random
        
        # Fixed prefix as requested
        prefix = "AL"
        
        # Number of digits after prefix (8 digits = 100 million possible combinations)
        num_digits = 8
        
        # Try to use product_id for more predictable barcodes, but pad to ensure length
        if product_id:
            # Format: AL + product_id padded to 8 digits
            # This makes barcodes more predictable for existing products
            numeric_part = str(product_id).zfill(num_digits)
            barcode = f"{prefix}{numeric_part}"
            
            # Check if this barcode already exists in the entire database (excluding current product and empty barcodes)
            query = Product.objects.filter(barcode=barcode).exclude(barcode='')
            if product_id:
                query = query.exclude(pk=product_id)
            if not query.exists():
                return barcode
        
        # For new products or if product_id format conflicts, generate random
        max_attempts = 100  # Increased attempts for better collision handling
        attempt = 0
        
        while attempt < max_attempts:
            # Generate random 8-digit number (00000000 to 99999999)
            numeric_part = ''.join([str(random.randint(0, 9)) for _ in range(num_digits)])
            barcode = f"{prefix}{numeric_part}"
            
            # Check entire database for uniqueness (excluding current product if editing and empty barcodes)
            query = Product.objects.filter(barcode=barcode).exclude(barcode='')
            if product_id:
                query = query.exclude(pk=product_id)
            exists = query.exists()
            
            if not exists:
                return barcode
            
            attempt += 1
        
        # If we still have collisions after max attempts, use a sequential approach
        # Get the highest existing numeric part for barcodes starting with "AL"
        # Check entire database for all barcodes starting with prefix (excluding empty barcodes)
        query = Product.objects.filter(barcode__startswith=prefix).exclude(barcode='')
        if product_id:
            query = query.exclude(pk=product_id)
        existing_barcodes = query.values_list('barcode', flat=True)
        
        # Extract numeric parts and find the maximum
        max_num = 0
        for existing_barcode in existing_barcodes:
            if existing_barcode.startswith(prefix) and len(existing_barcode) == len(prefix) + num_digits:
                try:
                    numeric_part_str = existing_barcode[len(prefix):]
                    num_value = int(numeric_part_str)
                    max_num = max(max_num, num_value)
                except (ValueError, IndexError):
                    continue
        
        # Generate next sequential number (with some randomization to avoid predictable patterns)
        next_num = (max_num + 1 + random.randint(1, 100)) % (10 ** num_digits)
        numeric_part = str(next_num).zfill(num_digits)
        barcode = f"{prefix}{numeric_part}"
        
        # Final check to ensure this is unique across entire database (excluding empty barcodes)
        query = Product.objects.filter(barcode=barcode).exclude(barcode='')
        if product_id:
            query = query.exclude(pk=product_id)
        if not query.exists():
            return barcode
        
        # Ultimate fallback: use timestamp-based approach
        from datetime import datetime
        timestamp_num = int(datetime.now().timestamp()) % (10 ** num_digits)
        numeric_part = str(timestamp_num).zfill(num_digits)
        barcode = f"{prefix}{numeric_part}"
        
        # Last check across entire database (excluding empty barcodes)
        query = Product.objects.filter(barcode=barcode).exclude(barcode='')
        if product_id:
            query = query.exclude(pk=product_id)
        if not query.exists():
            return barcode
        
        # If all else fails, add random suffix to timestamp
        final_suffix = ''.join([str(random.randint(0, 9)) for _ in range(4)])
        numeric_part = (str(timestamp_num)[:4] + final_suffix).zfill(num_digits)
        return f"{prefix}{numeric_part}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        original_barcode = self.barcode
        
        # Auto-generate barcode if not provided and business exists
        if (not self.barcode or self.barcode.strip() == "") and self.business_id:
            # For new products, generate a temporary barcode (will be regenerated after save)
            # For existing products, use their ID
            if is_new:
                # Generate initial barcode (might not be perfectly unique, but good enough)
                self.barcode = self.generate_barcode(business=self.business, product_id=None)
            else:
                # Existing product - use its ID for uniqueness
                self.barcode = self.generate_barcode(business=self.business, product_id=self.pk)
        
        # Save the product
        super().save(*args, **kwargs)
        
        # For new products, regenerate barcode with the new product ID to ensure uniqueness
        if is_new and self.barcode and self.pk:
            # Check if barcode already exists (should be rare, but possible)
            if Product.objects.filter(barcode=self.barcode).exclude(pk=self.pk).exists():
                # Regenerate with product ID for guaranteed uniqueness
                new_barcode = self.generate_barcode(business=self.business, product_id=self.pk)
                if new_barcode != self.barcode:
                    self.barcode = new_barcode
                    super().save(update_fields=["barcode"])

    # NEW: Logic for Stock Status Page
    @property
    def bulk_stock_status(self):
        """Returns the calculated bulk quantity (e.g., 1.00 Bag)"""
        if self.bulk_uom and self.default_bulk_size and self.default_bulk_size > 0:
            qty = (self.stock_qty or Decimal("0")) / self.default_bulk_size
            return f"{qty:g} {self.bulk_uom.code}"
        return ""

    def primary_image(self) -> "ProductImage | None":
        img = self.images.filter(is_primary=True, is_active=True, is_deleted=False).first()
        return img or self.images.filter(is_active=True, is_deleted=False).order_by("sort_order", "id").first()
    
    def __str__(self):
        return f"{self.name}"  


def _product_image_upload_to(instance, filename: str) -> str:
    product = instance.product
    bcode = getattr(product.business, "code", "global")
    sku = (product.sku or "nosku").replace("/", "_")
    now = timezone.localtime()
    stamp = now.strftime("%Y%m%d%H%M%S")
    return f"products/{bcode}/{sku}/{now.strftime('%Y')}/{now.strftime('%m')}/{stamp}_{filename}"

class ProductImage(TimeStampedBy):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images",
        db_index=True,
    )
    # Make image optional
    image = models.ImageField(
        upload_to=_product_image_upload_to,
        max_length=500,
        blank=True,   # <-- allow empty in forms/admin
        null=True,    # <-- allow NULL in DB (optional but keeps it explicit)
        help_text="Upload the product image file (JPG/PNG/WebP)."
    )
    alt_text   = models.CharField(max_length=255, blank=True, default="")
    is_primary = models.BooleanField(default=False, db_index=True)
    sort_order = models.PositiveIntegerField(default=0, db_index=True)

    class Meta:
        ordering = ["sort_order", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["product", "is_primary"]),
            models.Index(fields=["product", "sort_order"]),
        ]
        constraints = [
            UniqueConstraint(
                fields=["product"],
                condition=Q(is_primary=True),
                name="uniq_primary_image_per_product",
            ),
        ]

    def __str__(self):
        name = getattr(self.product, "name", "—")
        return f"{name} [{'PRIMARY' if self.is_primary else 'image'}]"

    def clean(self):
        # If you mark it as primary, then an image file must be present
        if self.is_primary and not self.image:
            raise ValidationError({"image": "Primary image must have a file uploaded."})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_primary:
            (ProductImage.objects
                .filter(product=self.product)
                .exclude(pk=self.pk)
                .update(is_primary=False))

# --------------------------------
# Staff (scoped to one business)
# --------------------------------
import secrets, string
from django.contrib.auth import get_user_model
from django.utils.text import slugify

class Staff(TimeStampedBy):
    class Roles(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Admin"
        MANAGER     = "manager",     "Manager"
        CASHIER     = "cashier",     "Cashier"
        ACCOUNTANT  = "accountant",  "Accountant"
        IT_MANAGER  = "it_manager",  "IT Manager"
        HELPER      = "helper",      "Helper"

    business = models.ForeignKey(
        Business,
        on_delete=models.PROTECT,
        related_name="staff",
        null=False, blank=False,
    )

    full_name = models.CharField(max_length=150, db_index=True)
    role      = models.CharField(max_length=30, choices=Roles.choices, default=Roles.HELPER)

    phone   = models.CharField(max_length=20, blank=True, default="")
    cnic    = models.CharField(max_length=25, blank=True, default="")
    address = models.TextField(blank=True, default="")

    has_software_access = models.BooleanField(default=False)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="staff_profile",
    )

    access_sales     = models.BooleanField(default=False)
    access_inventory = models.BooleanField(default=False)
    access_accounts  = models.BooleanField(default=False)

    joined_on      = models.DateField(null=True, blank=True)
    salary_start   = models.DateField(null=True, blank=True)
    monthly_salary = models.DecimalField(**DECIMAL_12_2, default=0)

    class Meta:
        indexes = [
            models.Index(fields=["business", "role"]),
            models.Index(fields=["business", "full_name"]),
            models.Index(fields=["phone"]),
            models.Index(fields=["cnic"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "phone"],
                name="uniq_staff_business_phone_when_set",
                condition=~Q(phone=""),
            ),
            models.UniqueConstraint(
                fields=["business", "cnic"],
                name="uniq_staff_business_cnic_when_set",
                condition=~Q(cnic=""),
            ),
        ]

    def __str__(self):
        return f"{self.business.code} / {self.full_name}"

    def clean(self):
        if not self.business_id:
            raise ValidationError("Please select a Business for this staff member.")
        if self.user_id and self.has_software_access and not self.user.is_active:
            raise ValidationError("Linked user is inactive. Activate the user or disable software access.")

    @staticmethod
    def _generate_password(length: int = 12) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def _suggest_username(self) -> str:
        base = slugify(f"{self.business.code}-{self.full_name}") or "user"
        base = base[:25]
        User = get_user_model()
        username = base
        i = 1
        while User.objects.filter(username=username).exists():
            suffix = f"-{i}"
            username = (base[: (25 - len(suffix))] + suffix)
            i += 1
        return username

    def provision_user(self, username: str | None = None, email: str = "", password: str | None = None):
        User = get_user_model()
        if self.user_id:
            return self.user, None
        if not username:
            username = self._suggest_username()
        if not password:
            password = self._generate_password()
        user = User.create_user(username=username, email=email or "", password=password) \
            if hasattr(User, "create_user") else User.objects.create_user(username=username, email=email or "", password=password)
        self.user = user
        self.has_software_access = True
        super(Staff, self).save(update_fields=["user", "has_software_access", "updated_at", "updated_by"])
        self.generated_password = password
        return user, password

    def revoke_access(self, deactivate_user: bool = False):
        self.has_software_access = False
        if self.user_id and deactivate_user:
            self.user.is_active = False
            self.user.save(update_fields=["is_active"])
        super(Staff, self).save(update_fields=["has_software_access", "updated_at", "updated_by"])

    def save(self, *args, **kwargs):
        if self.has_software_access and not self.user_id:
            username = self._suggest_username()
            password = self._generate_password()
            User = get_user_model()
            user = User.objects.create_user(username=username, email="", password=password)
            self.user = user
            self.generated_password = password
        super().save(*args, **kwargs)

# --------------------------------
# Cash / Bank (GLOBAL)
# --------------------------------
class BankAccount(TimeStampedBy):
    """
    Global/shared bank account. Not tied to any Business.
    """
    name            = models.CharField(max_length=100, help_text="e.g. HBL Current A/C")
    bank_name       = models.CharField(max_length=100, blank=True, default="")
    account_number  = models.CharField(max_length=50, blank=True, default="")
    branch          = models.CharField(max_length=100, blank=True, default="")
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    
    BANK            = "BANK"
    CASH            = "CASH"
    ACCOUNT_TYPES   = [(BANK, "Bank Account"), (CASH, "Cash in Hand")]
    account_type    = models.CharField(max_length=10, choices=ACCOUNT_TYPES, default=BANK)
    
    is_active       = models.BooleanField(default=True)
    business        = models.ForeignKey("Business", on_delete=models.CASCADE, related_name="bank_accounts", null=True, blank=True, help_text="Business this account belongs to. If NULL, it is global.")

    class Meta:
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["account_number"]),
            models.Index(fields=["is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["account_number"],
                name="uniq_bankaccount_acctnum_when_set",
                condition=~Q(account_number=""),
            ),
        ]

    def __str__(self):
        label = self.bank_name or "Bank"
        return f"{label} — {self.name}"

    @property
    def current_balance(self):
        agg = (
            CashFlow.objects
            .filter(bank_account=self)
            .aggregate(
                net=Sum(
                    Case(
                        When(flow_type=CashFlow.IN,  then=F("amount")),
                        When(flow_type=CashFlow.OUT, then=-F("amount")),
                        default=0,
                        output_field=DecimalField(max_digits=12, decimal_places=2),
                    )
                )
            )
        ).get("net") or Decimal("0.00")
        return (self.opening_balance or Decimal("0.00")) + agg

class CashFlow(TimeStampedBy):
    """
    Single row in the cash/bank ledger. If bank_account is NULL, it's physical CASH.
    GLOBAL (no business FK) as per your last code.
    """
    IN  = "in"
    OUT = "out"
    FLOW_TYPE = [(IN, "Cash In"), (OUT, "Cash Out")]

    date         = models.DateField(default=timezone.now, db_index=True)
    flow_type    = models.CharField(max_length=3, choices=FLOW_TYPE)
    amount       = models.DecimalField(max_digits=12, decimal_places=2)
    bank_account = models.ForeignKey(
        "BankAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cashflows",
    )
    description  = models.CharField(max_length=255, blank=True, default="")
    business     = models.ForeignKey("Business", on_delete=models.CASCADE, related_name="cash_flows", null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["flow_type"]),
            models.Index(fields=["bank_account"]),
        ]
        ordering = ["-date", "-id"]

    def clean(self):
        if self.amount is not None and self.amount <= 0:
            raise ValidationError("Amount must be positive.")

    def __str__(self):
        side = "Bank" if self.bank_account_id else "Cash"
        return f"{self.date} - {self.get_flow_type_display()} {self.amount} ({side})"

    # NEW: helper to get total physical cash in hand
    @classmethod
    def cash_in_hand(cls) -> Decimal:
        """
        Current total physical cash.
        Sum of all IN - OUT where bank_account is NULL.
        """
        agg = (
            cls.objects.filter(bank_account__isnull=True)
            .aggregate(
                net=Sum(
                    Case(
                        When(flow_type=cls.IN,  then=F("amount")),
                        When(flow_type=cls.OUT, then=-F("amount")),
                        default=0,
                        output_field=DecimalField(max_digits=12, decimal_places=2),
                    )
                )
            )
        )
        return agg.get("net") or Decimal("0.00")

class BankMovement(TimeStampedBy):
    """
    A single logical movement that can touch CASH and or BANK.
    writing matching rows to CashFlow so reports stay consistent.
    Not scoped to any Business.
    """
    DEPOSIT        = "deposit"         # cash -> bank
    CHEQUE_DEPOSIT = "cheque_deposit"  # cheque -> bank
    WITHDRAW       = "withdraw"        # bank -> cash
    TRANSFER       = "transfer"        # bank A -> bank B
    FEE            = "fee"             # bank fee (out)
    INTEREST       = "interest"        # bank interest (in)
    CHEQUE_PAYMENT = "cheque_payment"  # bank -> cheque to pay party / PO

    TYPES = [
        (DEPOSIT,        "Deposit (Cash -> Bank)"),
        (CHEQUE_DEPOSIT, "Deposit (Cheque -> Bank)"),
        (WITHDRAW,       "Withdraw (Bank -> Cash)"),
        (TRANSFER,       "Transfer (Bank -> Bank)"),
        (FEE,            "Bank Fee (Out)"),
        (INTEREST,       "Bank Interest (In)"),
        (CHEQUE_PAYMENT, "Cheque payment (Bank -> Party / Purchase Order)"),
    ]

    date          = models.DateField(default=timezone.now, db_index=True)
    movement_type = models.CharField(max_length=20, choices=TYPES)
    amount        = models.DecimalField(max_digits=12, decimal_places=2)

    # actors (global)
    from_bank = models.ForeignKey(
        "BankAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="outgoing_movements",
    )
    to_bank   = models.ForeignKey(
        "BankAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="incoming_movements",
    )

    # NEW: link to party and purchase order when paying by cheque
    party = models.ForeignKey(
        "Party",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="bank_movements",
    )
    purchase_order = models.ForeignKey(
        "PurchaseOrder",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="bank_movements",
    )

    method       = models.CharField(max_length=30, blank=True, default="", help_text="e.g. Cash, Cheque, Online")
    reference_no = models.CharField(max_length=100, blank=True, default="", help_text="Cheque or transaction ref if any")
    notes        = models.CharField(max_length=255, blank=True, default="")
    business     = models.ForeignKey("Business", on_delete=models.CASCADE, related_name="bank_movements", null=True, blank=True)

    # day closing flag
    is_day_closing = models.BooleanField(
        default=False,
        help_text="If checked with Deposit (Cash -> Bank). system will use current cash in hand."
    )

    # Link to the actual ledger rows so edits or deletes stay consistent
    cashflow_out = models.OneToOneField(
        "CashFlow",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="movement_out",
    )
    cashflow_in  = models.OneToOneField(
        "CashFlow",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="movement_in",
    )

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["movement_type"]),
        ]

    def __str__(self):
        return f"{self.get_movement_type_display()} - {self.amount} on {self.date}"

    def clean(self):
        # Allow amount to be empty or zero only when we are doing a day-closing deposit
        if (
            (self.amount is None or self.amount <= 0)
            and not (self.is_day_closing and self.movement_type == self.DEPOSIT)
        ):
            raise ValidationError("Amount must be positive.")

        if self.movement_type == self.DEPOSIT:
            # Cash -> Bank
            if not self.to_bank:
                raise ValidationError("Deposit requires a destination bank (to_bank).")

        elif self.movement_type == self.CHEQUE_DEPOSIT:
            # Cheque -> Bank
            if not self.to_bank:
                raise ValidationError("Cheque deposit requires a destination bank (to_bank).")

        elif self.movement_type == self.WITHDRAW:
            if not self.from_bank:
                raise ValidationError("Withdrawal requires a source bank (from_bank).")

        elif self.movement_type == self.TRANSFER:
            if not self.from_bank or not self.to_bank:
                raise ValidationError("Transfer requires both from_bank and to_bank.")
            if self.from_bank_id == self.to_bank_id:
                raise ValidationError("Cannot transfer to the same bank account.")

        elif self.movement_type in [self.FEE, self.INTEREST]:
            if not (self.from_bank or self.to_bank):
                raise ValidationError("Fee or Interest must reference at least one bank account.")

        elif self.movement_type == self.CHEQUE_PAYMENT:
            # Bank -> Cheque for paying a Party or PO
            errors = {}
            if not self.from_bank:
                errors["from_bank"] = "Cheque payment requires a source bank."
            if not self.party:
                errors["party"] = "Cheque payment requires a Party."
            if self.purchase_order and self.purchase_order.supplier_id != self.party_id:
                errors["purchase_order"] = "Selected Purchase Order does not belong to this Party."
            if errors:
                raise ValidationError(errors)

        # Day closing only makes sense for Deposit
        if self.is_day_closing and self.movement_type != self.DEPOSIT:
            raise ValidationError("Day closing can only be used with Deposit (Cash -> Bank).")

    @transaction.atomic
    def save(self, *args, **kwargs):
        creating = self.pk is None

        # If this is a day closing deposit. override amount with current cash in hand
        if self.is_day_closing and self.movement_type == self.DEPOSIT:
            cash = CashFlow.cash_in_hand()
            if cash <= Decimal("0.00"):
                raise ValidationError("No positive cash in hand to deposit.")
            self.amount = cash

        super().save(*args, **kwargs)

        out_kwargs, in_kwargs = None, None

        if self.movement_type == self.DEPOSIT:
            # Cash -> Bank
            out_kwargs = dict(
                date=self.date,
                flow_type=CashFlow.OUT,
                bank_account=None,
                amount=self.amount,
                description=f"Deposit to {self.to_bank}",
                business=self.business,
            )
            in_kwargs = dict(
                date=self.date,
                flow_type=CashFlow.IN,
                bank_account=self.to_bank,
                amount=self.amount,
                description="Cash deposit",
                business=self.business,
            )

        elif self.movement_type == self.CHEQUE_DEPOSIT:
            # Cheque -> Bank (only bank IN, no cash OUT)
            in_kwargs = dict(
                date=self.date,
                flow_type=CashFlow.IN,
                bank_account=self.to_bank,
                amount=self.amount,
                description=self.notes or f"Cheque deposit to {self.to_bank}",
                business=self.business,
            )

        elif self.movement_type == self.WITHDRAW:
            out_kwargs = dict(
                date=self.date,
                flow_type=CashFlow.OUT,
                bank_account=self.from_bank,
                amount=self.amount,
                description="Cash withdrawal",
                business=self.business,
            )
            in_kwargs = dict(
                date=self.date,
                flow_type=CashFlow.IN,
                bank_account=None,
                amount=self.amount,
                description=f"Withdraw from {self.from_bank}",
                business=self.business,
            )

        elif self.movement_type == self.TRANSFER:
            out_kwargs = dict(
                date=self.date,
                flow_type=CashFlow.OUT,
                bank_account=self.from_bank,
                amount=self.amount,
                description=f"Transfer to {self.to_bank}",
                business=self.business,
            )
            in_kwargs = dict(
                date=self.date,
                flow_type=CashFlow.IN,
                bank_account=self.to_bank,
                amount=self.amount,
                description=f"Transfer from {self.from_bank}",
                business=self.business,
            )

        elif self.movement_type == self.FEE:
            out_kwargs = dict(
                date=self.date,
                flow_type=CashFlow.OUT,
                bank_account=self.from_bank or self.to_bank,
                amount=self.amount,
                description="Bank fee",
                business=self.business,
            )

        elif self.movement_type == self.INTEREST:
            in_kwargs = dict(
                date=self.date,
                flow_type=CashFlow.IN,
                bank_account=self.to_bank or self.from_bank,
                amount=self.amount,
                description="Bank interest",
                business=self.business,
            )

        elif self.movement_type == self.CHEQUE_PAYMENT:
            # Bank -> Cheque paid to party / purchase order.
            po_part = ""
            if self.purchase_order_id:
                po_part = f" for PO #{self.purchase_order_id}"
            desc = f"Cheque payment to {self.party.display_name if self.party_id else ''}{po_part}".strip()
            out_kwargs = dict(
                date=self.date,
                flow_type=CashFlow.OUT,
                bank_account=self.from_bank,
                amount=self.amount,
                description=desc,
                business=self.business,
            )

        # Upsert OUT
        if out_kwargs:
            if self.cashflow_out_id:
                cf = self.cashflow_out
                cf.date = out_kwargs["date"]
                cf.flow_type = out_kwargs["flow_type"]
                cf.bank_account = out_kwargs["bank_account"]
                cf.amount = out_kwargs["amount"]
                cf.description = out_kwargs["description"]
                cf.business = out_kwargs.get("business")
                cf.updated_by = self.updated_by
                cf.save(
                    update_fields=[
                        "date",
                        "flow_type",
                        "bank_account",
                        "amount",
                        "description",
                        "business",
                        "updated_at",
                        "updated_by",
                    ]
                )
            else:
                self.cashflow_out = CashFlow.objects.create(
                    created_by=self.created_by,
                    updated_by=self.updated_by,
                    **out_kwargs,
                )
        else:
            if self.cashflow_out_id:
                self.cashflow_out.delete()
                self.cashflow_out = None

        # Upsert IN
        if in_kwargs:
            if self.cashflow_in_id:
                cf = self.cashflow_in
                cf.date = in_kwargs["date"]
                cf.flow_type = in_kwargs["flow_type"]
                cf.bank_account = in_kwargs["bank_account"]
                cf.amount = in_kwargs["amount"]
                cf.description = in_kwargs["description"]
                cf.business = in_kwargs.get("business")
                cf.updated_by = self.updated_by
                cf.save(
                    update_fields=[
                        "date",
                        "flow_type",
                        "bank_account",
                        "amount",
                        "description",
                        "business",
                        "updated_at",
                        "updated_by",
                    ]
                )
            else:
                self.cashflow_in = CashFlow.objects.create(
                    created_by=self.created_by,
                    updated_by=self.updated_by,
                    **in_kwargs,
                )
        else:
            if self.cashflow_in_id:
                self.cashflow_in.delete()
                self.cashflow_in = None

        if creating or "force_update_links" in kwargs:
            super().save(update_fields=["cashflow_out", "cashflow_in", "updated_at", "updated_by"])

        # Update summary if business set
        if self.business_id:
            from .signals import update_business_summary
            update_business_summary(self.business_id)


# --------------------------------
# Stock transaction (optional; unchanged)
# --------------------------------

class StockTransaction(TimeStampedBy):
    IN      = "in"
    OUT     = "out"
    RETURN  = "return"
    TYPES = [(IN, "In"), (OUT, "Out"), (RETURN, "Return")]

    business   = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="stock_transactions")
    date       = models.DateField(default=timezone.now, db_index=True)
    movement   = models.CharField(max_length=10, choices=TYPES)
    product    = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_transactions")
    uom        = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="stock_transactions")
    quantity   = models.DecimalField(**DECIMAL_18_6, validators=[MinValueValidator(0)])
    reference  = models.CharField(max_length=100, blank=True, default="")
    notes      = models.CharField(max_length=255, blank=True, default="")
    po_item    = models.ForeignKey("PurchaseOrderItem", on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="stock_transactions")

    class Meta:
        indexes = [
            models.Index(fields=["business", "date"]),
            models.Index(fields=["movement"]),
            models.Index(fields=["product"]),
        ]
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.business.code} — {self.movement.upper()} — {self.product.name} x {self.quantity}"

# --------------------------------
# Purchase Orders (+ bridge payments)
# --------------------------------
class PurchaseOrder(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("received", "Received"),
    ]

    business   = models.ForeignKey(
        Business,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )
    supplier   = models.ForeignKey(
        Party,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )
    status     = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
    )

    # optional warehouse for this PO
    warehouse  = models.ForeignKey(
        "Warehouse",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="purchase_orders",
    )

    # money
    total_cost       = models.DecimalField(**DECIMAL_12_2, default=Decimal("0.00"))
    tax_percent      = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    net_total        = models.DecimalField(**DECIMAL_12_2, default=Decimal("0.00"))

    # metadata
    notes      = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="po_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="po_updated",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    is_active  = models.BooleanField(default=True, db_index=True)
    is_deleted = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        supplier_name = getattr(self.supplier, "display_name", "-")
        return f"PO #{self.pk or '-'} - {supplier_name}"

    # helper so items know if this PO uses a warehouse
    def uses_warehouse(self) -> bool:
        return bool(getattr(self, "warehouse_id", None))

    # ---------- totals and payments ----------

    def recompute_totals(self):
        # 1. Sum Items
        subtotal = sum((it.quantity * it.unit_price) for it in self.items.all())
        self.total_cost = _money_q(subtotal)

        # 2. Apply Tax/Discount
        tax = (self.tax_percent / 100) * self.total_cost
        disc = (self.discount_percent / 100) * self.total_cost
        
        # 3. Sum Linked Expenses
        # Only sum expenses that aren't marked for deletion in the current transaction
        expense_total = self.expenses.aggregate(s=models.Sum('amount'))['s'] or Decimal("0.00")

        # 4. Final Net Total
        self.net_total = _money_q(self.total_cost + tax - disc + expense_total)

    def distribute_expenses(self):
        """
        Distribute expenses marked with divide_per_unit across items.
        Updates item.landing_unit_price.
        """
        from decimal import Decimal
        
        # 1. Sum expenses to distribute
        dist_expenses = self.expenses.filter(divide_per_unit=True).aggregate(s=Sum('amount'))['s'] or Decimal("0.00")
        
        # 2. If no expenses to distribute, landing price is just unit price
        if dist_expenses <= 0:
            for item in self.items.all():
                if item.landing_unit_price != item.unit_price:
                    item.landing_unit_price = item.unit_price
                    item.save(update_fields=['landing_unit_price'])
            return

        # 3. Calculate total base units
        # We distribute based on quantity converted to the lowest unit (base unit)
        total_base_qty = Decimal("0.00")
        items = list(self.items.all())
        for item in items:
            total_base_qty += (item.quantity or Decimal("0")) * (item.size_per_unit or Decimal("1"))
            
        if total_base_qty <= 0:
            return

        # 4. Calculate expense per base unit
        expense_per_base_unit = dist_expenses / total_base_qty

        # 5. Apply to each item
        for item in items:
            base_unit_dist = expense_per_base_unit
            # Item's landing price is its unit price + (dist cost * size_per_unit)
            # This works because unit_price is also per 'unit' (Bag/KG/etc)
            item.landing_unit_price = (item.unit_price or Decimal("0.00")) + (expense_per_base_unit * (item.size_per_unit or Decimal("1")))
            item.save(update_fields=['landing_unit_price'])

    @property
    def paid_total(self) -> Decimal:
        """
        Sum of all applied payments for this PO.
        """
        agg = self.payment_applications.aggregate(s=Sum("amount"))
        return agg["s"] or Decimal("0.00")

    @property
    def balance_due(self) -> Decimal:
        """
        Remaining amount after applied payments.
        """
        return (self.net_total or Decimal("0.00")) - self.paid_total

    def apply_payment(self, payment: "Payment", amount: Decimal):
        """
        Apply a Payment.OUT against this Purchase Order.
        Creates or updates PurchaseOrderPayment row.
        """
        app, created = PurchaseOrderPayment.objects.get_or_create(
            purchase_order=self,
            payment=payment,
            defaults={
                "amount": Decimal("0.00"),
                "created_by": payment.created_by,
                "updated_by": payment.updated_by,
            },
        )
        app.amount = (app.amount or Decimal("0.00")) + (amount or Decimal("0.00"))
        app.full_clean()
        app.save()
        return app

class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product    = models.ForeignKey(Product, on_delete=models.PROTECT)

    # NEW: Store which unit was used (Bag or KG)
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, null=True)
    
    # NEW: Store the multiplier (e.g. 50.00 for a 50kg bag)
    size_per_unit = models.DecimalField(
        max_digits=18, decimal_places=6, default=Decimal("1.000000")
    )
    quantity   = models.DecimalField(max_digits=18, decimal_places=6)
    unit_price = models.DecimalField(**DECIMAL_12_2)

    landing_unit_price = models.DecimalField(
        **DECIMAL_12_2, null=True, blank=True,
        help_text="Unit price including distributed expenses (Landing Cost)"
    )
    sale_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Sale price for this item (in the unit selected). Will be converted to lower unit if bulk unit is used."
    )

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.purchase_order:
            self.purchase_order.distribute_expenses()
            self.purchase_order.recompute_totals()
            self.purchase_order.save(update_fields=['total_cost', 'net_total', 'updated_at'])

    def delete(self, *args, **kwargs):
        po = self.purchase_order
        super().delete(*args, **kwargs)
        if po:
            po.distribute_expenses()
            po.recompute_totals()
            po.save(update_fields=['total_cost', 'net_total', 'updated_at'])

    def total_cost(self):
        q = self.quantity or Decimal("0")
        p = self.unit_price or Decimal("0")
        return q * p

    def __str__(self):
        pname = getattr(self.product, "name", "-")
        return f"{self.quantity or 0} x {pname}"

    # No stock logic here now. everything status based is handled in the views
    @transaction.atomic
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)

class PurchaseReturn(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processed", "Processed"),
    ]

    business   = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="purchase_returns")
    supplier   = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="purchase_returns")
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    # money
    total_cost       = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))  # subtotal
    tax_percent      = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    net_total        = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    # meta
    notes      = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pr_created")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pr_updated")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    is_active  = models.BooleanField(default=True, db_index=True)
    is_deleted = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"PR #{self.pk or '—'} — {getattr(self.supplier, 'display_name', '—')}"

    def recompute_totals(self):
        subtotal = Decimal("0.00")
        for it in self.items.all():
            q = it.quantity or Decimal("0")
            p = it.unit_price or Decimal("0")
            subtotal += (q * p)

        self.total_cost = subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        tax_pct  = (self.tax_percent or Decimal("0")) / Decimal("100")
        disc_pct = (self.discount_percent or Decimal("0")) / Decimal("100")

        tax_amt  = (self.total_cost * tax_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        disc_amt = (self.total_cost * disc_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        self.net_total = (self.total_cost + tax_amt - disc_amt).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def refunded_total(self):
        agg = self.refund_applications.aggregate(s=Sum("amount"))
        return agg["s"] or Decimal("0.00")

    @property
    def refund_remaining(self):
        return (self.net_total or Decimal("0.00")) - self.refunded_total

    def apply_refund(self, payment: "Payment", amount: Decimal):
        """
        Apply a receipt (Payment.IN) to this purchase return.
        Creates/updates the bridge row and validates caps.
        """
        app, created = PurchaseReturnRefund.objects.get_or_create(
            purchase_return=self,
            payment=payment,
            defaults={
                "amount": Decimal("0.00"),
                "created_by": payment.created_by,
                "updated_by": payment.updated_by,
            },
        )
        app.amount = (app.amount or Decimal("0.00")) + (amount or Decimal("0.00"))
        app.full_clean()
        app.save()
        return app

class PurchaseReturnItem(models.Model):
    purchase_return = models.ForeignKey(PurchaseReturn, on_delete=models.CASCADE, related_name="items")
    product         = models.ForeignKey(Product, on_delete=models.PROTECT)
    
    # Store which unit was used (Bag or KG)
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, null=True)
    
    # Store the multiplier (e.g. 50.00 for a 50kg bag)
    size_per_unit = models.DecimalField(
        max_digits=18, decimal_places=6, default=Decimal("1.000000")
    )
    quantity        = models.DecimalField(max_digits=18, decimal_places=6)  # qty being returned
    unit_price      = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["id"]

    def total_cost(self):
        q = self.quantity or Decimal("0")
        p = self.unit_price or Decimal("0")
        return q * p

    def __str__(self):
        return f"{self.quantity or 0} x {getattr(self.product, 'name', '—')}"

    # -------- STOCK ADJUSTMENT HELPERS (for returns) --------
    def _is_processed(self) -> bool:
        try:
            return (self.purchase_return.status or "").lower() == "processed"
        except Exception:
            return False

    @staticmethod
    def _add_stock(product_id, delta: Decimal):
        if not delta:
            return
        (Product.objects
         .select_for_update()
         .filter(pk=product_id)
         .update(stock_qty=F("stock_qty") + delta))

    @transaction.atomic
    def save(self, *args, **kwargs):
        creating = self.pk is None
        old_product_id = None
        old_qty = Decimal("0")

        if not creating:
            prev = (PurchaseReturnItem.objects
                    .select_for_update()
                    .only("product_id", "quantity")
                    .get(pk=self.pk))
            old_product_id = prev.product_id
            old_qty = prev.quantity or Decimal("0")

        super().save(*args, **kwargs)

        # Adjust stock only when the return is processed
        if not self._is_processed():
            return

        new_product_id = self.product_id
        new_qty = self.quantity or Decimal("0")

        if creating:
            # returning to supplier → stock OUT
            self._add_stock(new_product_id, -new_qty)
        else:
            if old_product_id != new_product_id:
                if old_product_id:
                    self._add_stock(old_product_id, +old_qty)   # undo previous OUT
                if new_product_id:
                    self._add_stock(new_product_id, -new_qty)   # apply new OUT
            else:
                delta = new_qty - old_qty
                if delta:
                    # increase returned qty → subtract more; decrease → add back
                    self._add_stock(new_product_id, -delta)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        # Deleting an already-processed return item should add stock back
        if self._is_processed():
            qty = self.quantity or Decimal("0")
            if qty and self.product_id:
                (Product.objects
                 .select_for_update()
                 .filter(pk=self.product_id)
                 .update(stock_qty=F("stock_qty") + qty))
        super().delete(*args, **kwargs)

class PurchaseReturnRefund(TimeStampedBy):
    """
    Bridge that applies (part of) a Payment to a Purchase Return.
    Allows partials, multiple receipts per return, and one receipt across many returns.
    """
    purchase_return = models.ForeignKey(
        "PurchaseReturn",
        on_delete=models.CASCADE,
        related_name="refund_applications"  # <- matches PurchaseReturn.refunded_total
    )
    payment = models.ForeignKey(
        "Payment",
        on_delete=models.CASCADE,
        related_name="applied_purchase_returns"
    )
    amount = models.DecimalField(**DECIMAL_12_2, validators=[MinValueValidator(0)])

    class Meta:
        indexes = [
            models.Index(fields=["purchase_return"]),
            models.Index(fields=["payment"]),
        ]
        unique_together = [("purchase_return", "payment")]  # one row per pair; increase amount as needed

    def __str__(self):
        return f"PR#{self.purchase_return_id} ⇄ Payment#{self.payment_id} — {self.amount}"

    def _current_amount_if_edit(self):
        if self.pk:
            try:
                old = PurchaseReturnRefund.objects.get(pk=self.pk)
                return old.amount
            except PurchaseReturnRefund.DoesNotExist:
                return Decimal("0.00")
        return Decimal("0.00")

    def clean(self):
        if self.amount and self.amount <= 0:
            raise ValidationError("Applied amount must be positive.")

        # Refunds must be receipts (money coming IN from the supplier)
        if self.payment.direction != Payment.IN:
            raise ValidationError("Only IN (receipt) payments can be applied to Purchase Returns.")

        # Must be same business
        if self.payment.business_id != self.purchase_return.business_id:
            raise ValidationError("Payment and Purchase Return must belong to the same business.")

        # Caps: cannot exceed payment remaining or PR balance (while allowing edits)
        reuse = self._current_amount_if_edit()
        if self.amount > (self.payment.remaining_unapplied + reuse):
            raise ValidationError("Applied amount exceeds the payment's remaining balance.")
        if self.amount > (self.purchase_return.refund_remaining + reuse):
            raise ValidationError("Applied amount exceeds the Purchase Return balance.")

# --------------------------------
# NEW: Payments (generic) + Bridge to PurchaseOrder 
# --------------------------------

class Payment(TimeStampedBy):
    """
    Generic payment/receipt with a Party.
    direction=OUT -> we pay vendor (use for Purchase Orders, Purchase Returns refunds, etc.)
    direction=IN  -> we receive from customer (use for Sales Orders, Invoices, Sales Returns refunds, etc.)
    """
    IN  = "in"
    OUT = "out"
    DIRECTIONS = [(IN, "In (Receipt)"), (OUT, "Out (Payment)")]

    CASH = "cash"
    BANK = "bank"
    SOURCES = [(CASH, "Cash"), (BANK, "Bank")]

    # High level method shown to user
    class PaymentMethod(models.TextChoices):
        CASH   = "cash",   "Cash"
        BANK   = "bank",   "Bank Transfer"
        CARD   = "card",   "Card Payment"
        CHEQUE = "cheque", "Cheque"

    # Only for cheque. pending / deposited
    class ChequeStatus(models.TextChoices):
        PENDING   = "pending",   "Pending"
        DEPOSITED = "deposited", "Deposited"

    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
        db_index=True,
    )

    # Only used when payment_method = CHEQUE
    cheque_status = models.CharField(
        max_length=20,
        choices=ChequeStatus.choices,
        blank=True,
        default="",
        help_text="Only used for cheque payments. Pending / Deposited.",
    )

    business       = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="payments")
    date           = models.DateField(default=timezone.now, db_index=True)
    party          = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="payments")
    direction      = models.CharField(max_length=3, choices=DIRECTIONS, db_index=True)
    amount         = models.DecimalField(**DECIMAL_12_2, validators=[MinValueValidator(0)])
    description    = models.CharField(max_length=255, blank=True, default="")
    reference      = models.CharField(max_length=100, blank=True, default="")

    # low level source for cashbook. cash vs bank ledger
    payment_source = models.CharField(
        max_length=10,
        choices=SOURCES,
        default=CASH,
        db_index=True,
    )
    bank_account   = models.ForeignKey(
        "BankAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )

    cashflow = models.OneToOneField(
        "CashFlow",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="linked_payment",
    )

    class Meta:
        indexes = [
            models.Index(fields=["business", "date"]),
            models.Index(fields=["party"]),
            models.Index(fields=["direction"]),
            models.Index(fields=["payment_source"]),
        ]
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.business.code} - {self.get_direction_display()} - {self.party.display_name} - {self.amount}"

    def clean(self):
        errors = {}

        # normal amount validation
        if self.amount and self.amount <= 0:
            errors["amount"] = "Amount must be positive."

        # map payment_method -> payment_source automatically
        # cash -> cash ledger. bank/cheque -> bank ledger
        if self.payment_method == self.PaymentMethod.CASH:
            self.payment_source = self.CASH
        else:
            self.payment_source = self.BANK

        # cheque status handling
        if self.payment_method == self.PaymentMethod.CHEQUE:
            # default to Pending if not set
            if not self.cheque_status:
                self.cheque_status = self.ChequeStatus.PENDING
        else:
            # non cheque payments should not carry cheque_status
            self.cheque_status = ""

        # bank transfer. always needs a bank account
        if self.payment_method == self.PaymentMethod.BANK and not self.bank_account_id:
            errors["bank_account"] = "Please select a Bank Account for bank transfer."

        # cheque business rules
        if self.payment_method == self.PaymentMethod.CHEQUE:
            # only deposited cheques must have a bank account
            if (
                self.cheque_status == self.ChequeStatus.DEPOSITED
                and not self.bank_account_id
            ):
                errors["bank_account"] = "Please select a Bank Account for deposited cheques."

        # for cash. never keep a bank account
        if self.payment_source == self.CASH:
            self.bank_account = None

        if errors:
            raise ValidationError(errors)

    # ---------- IMPORTANT PART (unchanged logic) ----------
    @property
    def applied_total(self):
        """
        Total applied amount from this Payment across:
        - Purchase Orders (OUT)
        - Purchase Returns (IN)
        - Sales Orders (IN)
        - Sales Invoices (IN)
        - Sales Returns (OUT)
        """
        def agg(qs):
            return qs.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")

        total = Decimal("0.00")

        # Purchases side
        if hasattr(self, "applied_purchase_orders"):
            total += agg(self.applied_purchase_orders)
        if hasattr(self, "applied_purchase_returns"):
            total += agg(self.applied_purchase_returns)

        # Sales side
        if hasattr(self, "applied_sales_orders"):
            total += agg(self.applied_sales_orders)
        if hasattr(self, "applied_sales_invoices"):
            total += agg(self.applied_sales_invoices)
        if hasattr(self, "applied_sales_returns"):
            total += agg(self.applied_sales_returns)

        return total

    @property
    def remaining_unapplied(self):
        """
        How much of this payment is still free to apply to orders/returns.
        """
        return (self.amount or Decimal("0.00")) - self.applied_total
    
    @transaction.atomic
    def save(self, *args, **kwargs):
        from .models import CashFlow
        
        # 1. Handle is_deleted: if marked deleted, remove CashFlow and return
        if getattr(self, "is_deleted", False):
            if self.cashflow_id:
                cf = self.cashflow
                self.cashflow = None
                super().save(update_fields=["cashflow", "updated_at", "updated_by"])
                cf.delete()
            else:
                super().save(*args, **kwargs)
            return

        # 2. Logic to determine if we should create/update CashFlow
        # Cheques only impact CashFlow when they are DEPOSITED
        should_mirror = True
        if self.payment_method == self.PaymentMethod.CHEQUE and self.cheque_status != self.ChequeStatus.DEPOSITED:
            should_mirror = False
        
        # If amount is 0, we don't really need a ledger entry (or we can delete old one)
        if (self.amount or 0) <= 0:
            should_mirror = False

        if not should_mirror:
            if self.cashflow_id:
                cf = self.cashflow
                self.cashflow = None
                super().save(update_fields=["cashflow", "updated_at", "updated_by"])
                cf.delete()
            else:
                super().save(*args, **kwargs)
            return

        # 3. Upsert CashFlow
        flow_type = CashFlow.IN if self.direction == self.IN else CashFlow.OUT
        # For Bank source, link the bank account; for Cash source, bank_account is None (physical cash)
        cf_bank = self.bank_account if self.payment_source == self.BANK else None
        desc = self.description or self.reference or f"{self.get_direction_display()} - {self.party.display_name}"

        if not self.cashflow_id:
            cf = CashFlow.objects.create(
                date=self.date,
                flow_type=flow_type,
                amount=self.amount,
                bank_account=cf_bank,
                description=desc,
                business=self.business,
                created_by=self.created_by,
                updated_by=self.updated_by,
            )
            self.cashflow = cf
            super().save(*args, **kwargs)
        else:
            cf = self.cashflow
            cf.date = self.date
            cf.flow_type = flow_type
            cf.amount = self.amount
            cf.bank_account = cf_bank
            cf.description = desc
            cf.business = self.business
            cf.updated_by = self.updated_by
            cf.save(update_fields=["date", "flow_type", "amount", "bank_account", "description", "business", "updated_at", "updated_by"])
            super().save(*args, **kwargs)
        
        # Trigger summary update
        if self.business_id:
            from .signals import update_business_summary
            update_business_summary(self.business_id)

    def delete(self, *args, **kwargs):
        cf = self.cashflow
        biz_id = self.business_id
        super().delete(*args, **kwargs)
        if cf:
            cf.delete()
        if biz_id:
            from .signals import update_business_summary
            update_business_summary(biz_id)
    # ---------- END PART ----------

class PurchaseOrderPayment(TimeStampedBy):
    """
    Bridge that applies (part of) a Payment to a Purchase Order.
    Allows partials, multiple payments per PO, and one payment across many POs.
    """
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="payment_applications")
    payment        = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="applied_purchase_orders")
    amount         = models.DecimalField(**DECIMAL_12_2, validators=[MinValueValidator(0)])

    class Meta:
        indexes = [
            models.Index(fields=["purchase_order"]),
            models.Index(fields=["payment"]),
        ]
        unique_together = [("purchase_order", "payment")]  # one bridge row per pair; increase amount as needed

    def __str__(self):
        return f"PO#{self.purchase_order_id} ⇄ Payment#{self.payment_id} — {self.amount}"

    def _current_amount_if_edit(self):
        if self.pk:
            try:
                old = PurchaseOrderPayment.objects.get(pk=self.pk)
                return old.amount
            except PurchaseOrderPayment.DoesNotExist:
                return Decimal("0.00")
        return Decimal("0.00")

    def clean(self):
        if self.amount and self.amount <= 0:
            raise ValidationError("Applied amount must be positive.")
        if self.payment.direction != Payment.OUT:
            raise ValidationError("Only OUT (vendor) payments can be applied to Purchase Orders.")
        if self.payment.business_id != self.purchase_order.business_id:
            raise ValidationError("Payment and Purchase Order must belong to the same business.")

        # caps: cannot exceed payment remaining or PO balance
        reuse = self._current_amount_if_edit()
        if self.amount > self.payment.remaining_unapplied + reuse:
            raise ValidationError("Applied amount exceeds the payment's remaining balance.")
        if self.amount > self.purchase_order.balance_due + reuse:
            raise ValidationError("Applied amount exceeds the Purchase Order balance.")

# --------------------------------
# Expenses
# --------------------------------

class ExpenseCategory(models.TextChoices):
    SALARY      = "salary",      "Salary"
    FREIGHT     = "freight",     "Freight/Kiraya"  # The attribute is 'FREIGHT'
    ELECTRICITY = "electricity", "Electricity"
    GAS         = "gas",         "Gas"
    STATIONERY  = "stationery",  "Stationery"
    MAINTENANCE = "maintenance", "Maintenance"
    TEA_AND_LUNCH    = "tea_and_lunch",    "Tea & Lunch"
    ZAKAT    = "zakat",    "Zakat"
    SHOP_KHARCHA   = "shop_kharcha",   "Shop Kharcha"
    TRANSPORT     = "transport",    "Transport"
    HOME_KHARCHA   = "home_kharcha",   "Home Kharcha"
    PURCHASE = "purchase", "Purchases/Other Items"
    OTHER       = "other",       "Other"

def _expense_upload_to(instance, filename: str) -> str:
    # /expenses/<business-code>/<YYYY>/<MM>/<filename>
    yyyy = timezone.now().strftime("%Y")
    mm = timezone.now().strftime("%m")
    bcode = getattr(instance.business, "code", "global")
    return f"expenses/{bcode}/{yyyy}/{mm}/{filename}"

class Expense(TimeStampedBy):
    """
    A business-scoped operating expense.
    Every save mirrors to CashFlow (OUT) so your cash/bank ledger stays consistent.
    BankAccount remains GLOBAL per your design.
    """
    CASH = "cash"
    BANK = "bank"
    PAYMENT_SOURCE = [(CASH, "Cash"), (BANK, "Bank")]

    # scope & basic
    business = models.ForeignKey(
        Business,
        on_delete=models.PROTECT,
        related_name="expenses",
        null=True,
        blank=True
    )    
    date        = models.DateField(default=timezone.now, db_index=True)
    category    = models.CharField(max_length=20, choices=ExpenseCategory.choices, db_index=True)
    amount      = models.DecimalField(**DECIMAL_12_2, validators=[MinValueValidator(0)])
    description = models.CharField(max_length=255, blank=True, default="")
    reference   = models.CharField(max_length=100, blank=True, default="")  # bill/invoice/ref
    attachment  = models.FileField(upload_to=_expense_upload_to, null=True, blank=True)

    # links
    party       = models.ForeignKey(Party,  on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses")
    staff       = models.ForeignKey(Staff,  on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses")
    purchase_order = models.ForeignKey("PurchaseOrder", on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses")
    # payment side
    payment_source = models.CharField(max_length=10, choices=PAYMENT_SOURCE, default=CASH, db_index=True)
    bank_account   = models.ForeignKey("BankAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses")
    is_paid        = models.BooleanField(default=True, help_text="Checked if this expense is already paid (e.g. at the time of purchase)")
    payment        = models.ForeignKey("Payment", on_delete=models.SET_NULL, null=True, blank=True, related_name="linked_po_expenses")

    # mirror to cashbook
    cashflow    = models.OneToOneField("CashFlow", on_delete=models.SET_NULL, null=True, blank=True, related_name="linked_expense")
    divide_per_unit = models.BooleanField(
            default=False,
            help_text="If checked, this expense will be distributed across all PO items per unit"
        )   
    class Meta:
        indexes = [
            models.Index(fields=["business", "date"]),
            models.Index(fields=["business", "category"]),
            models.Index(fields=["payment_source"]),
        ]
        ordering = ["-date", "-id"]

    def __str__(self):
        biz_code = getattr(self.business, "code", "—")
        return f"{biz_code} — {self.get_category_display()} — {self.amount} on {self.date}"

    def _infer_business_if_missing(self):
        """
        If business is not provided, try to infer it from related objects.
        Priority: staff > purchase_order > party.default_business
        """
        if self.business_id:
            return
        if getattr(self, "staff_id", None) and getattr(self.staff, "business_id", None):
            self.business = self.staff.business
            return
        if getattr(self, "purchase_order_id", None) and getattr(self.purchase_order, "business_id", None):
            self.business = self.purchase_order.business
            return
        if getattr(self, "party_id", None) and getattr(self.party, "default_business_id", None):
            self.business = self.party.default_business

    # ---- helpers ----
    @staticmethod
    def _requires_party(cat: str) -> bool:
        return cat in {
            ExpenseCategory.ELECTRICITY,
            ExpenseCategory.GAS,
            ExpenseCategory.PURCHASE,
            ExpenseCategory.STATIONERY,
            ExpenseCategory.MAINTENANCE,
            ExpenseCategory.SOFTWARE,
        }

    # ---- validation ----
    def clean(self):
        from django.core.exceptions import ValidationError

        if self.amount is not None and self.amount <= 0:
            raise ValidationError("Amount must be positive.")

        # Party required ONLY for Purchases/Other Items
        if (self.category == ExpenseCategory.PURCHASE) and not self.party_id:
            raise ValidationError({"party": "Supplier/Party is required for Purchases/Other Items."})

        # Staff required for Salary (unchanged)
        if self.category == ExpenseCategory.SALARY and not self.staff_id:
            raise ValidationError({"staff": "Staff is required for Salary."})

        # Payment source rules
        if self.payment_source == self.BANK and not self.bank_account_id:
            raise ValidationError({"bank_account": "Please select a Bank Account for bank-paid expenses."})
        if self.payment_source == self.CASH:
            self.bank_account = None 
    # ---- cashbook sync -----
    
    @transaction.atomic
    def save(self, *args, **kwargs):
        # Infer business again just in case save() is called without full clean()
        if not self.business_id:
            self._infer_business_if_missing()

        creating = self.pk is None
        super().save(*args, **kwargs)

        # Compose description
        parts = [f"Expense: {self.get_category_display()}"]
        if self.description:
            parts.append(self.description)
        if self.reference:
            parts.append(f"Ref: {self.reference}")
        if self.party_id:
            parts.append(f"Party: {self.party.display_name}")
        if self.staff_id and self.category == ExpenseCategory.SALARY:
            parts.append(f"Staff: {self.staff.full_name}")
        desc = " — ".join(parts)

        cf_bank = self.bank_account if self.payment_source == self.BANK else None

        # We record CashFlow for all cash/bank expenses to match dashboard stats,
        # even if is_paid is False (treating the source as the primary indicator).
        if not self.is_paid and self.payment_source not in [self.CASH, self.BANK]:
            if self.cashflow_id:
                cf = self.cashflow
                self.cashflow = None
                super().save(update_fields=["cashflow", "updated_at", "updated_by"])
                cf.delete()
            return

        # If this is an "Instant Payment" expense linked to a Payment object, 
        # we skip creating a CashFlow here because the Payment object will handle it.
        if self.is_paid and self.payment_id:
            if self.cashflow_id:
                cf = self.cashflow
                self.cashflow = None
                super().save(update_fields=["cashflow", "updated_at", "updated_by"])
                cf.delete()
            return

        if not self.cashflow_id:
            cf = CashFlow.objects.create(
                date=self.date,
                flow_type=CashFlow.OUT,
                amount=self.amount,
                bank_account=cf_bank,
                description=desc,
                business=self.business,
                created_by=self.created_by,
                updated_by=self.updated_by,
            )
            self.cashflow = cf
            super().save(update_fields=["cashflow", "updated_at", "updated_by"])
        else:
            cf = self.cashflow
            cf.date = self.date
            cf.flow_type = CashFlow.OUT
            cf.amount = self.amount
            cf.bank_account = cf_bank
            cf.description = desc
            cf.business = self.business
            cf.updated_by = self.updated_by
            cf.save(update_fields=["date", "flow_type", "amount", "bank_account", "description", "business", "updated_at", "updated_by"])

        # Automation: If linked to PurchaseOrder, re-distribute expenses
        if self.purchase_order:
            self.purchase_order.distribute_expenses()
            self.purchase_order.recompute_totals()
            self.purchase_order.save(update_fields=['total_cost', 'net_total', 'updated_at'])

    @transaction.atomic
    def delete(self, *args, **kwargs):
        cf = self.cashflow
        po = self.purchase_order
        super().delete(*args, **kwargs)
        if cf:
            cf.delete()
        if po:
            po.distribute_expenses()
            po.recompute_totals()
            po.save(update_fields=['total_cost', 'net_total', 'updated_at'])

# ============================
# SALES — Orders / Invoices / Returns
# ============================

from django.db import models, transaction
from django.db.models import Sum, F, Q, DecimalField
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal, ROUND_HALF_UP

# Reuse:
# - TimeStampedBy, Business, Party, Product, UnitOfMeasure (if you want UOM on lines)
# - DECIMAL_12_2, DECIMAL_18_6
# - Payment (direction IN for receipts, OUT for refunds)
# - StockTransaction (optional — shown as comments if you want to log)
# ----------------------------
# Utilities
# ----------------------------

def _money_q(v: Decimal) -> Decimal:
    return (v or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _next_invoice_no(business: "Business") -> str:
    """
    Simple, human-readable invoice number:
    <BUSCODE>-<YYYYMMDD>-<HHMMSS>-<id-ish>
    Replace with your own sequence if you prefer.
    """
    ts = timezone.localtime()
    stub = f"{business.code}-{ts.strftime('%Y%m%d')}-{ts.strftime('%H%M%S')}"
    return stub


# ----------------------------
# SALES ORDER
# ----------------------------

class SalesOrder(TimeStampedBy):
    class Status(models.TextChoices):
        OPEN       = "open",       "Open"
        FULFILLED  = "fulfilled",  "Fulfilled"
        CANCELLED  = "cancelled",  "Cancelled"

    business   = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="sales_orders")
    customer   = models.ForeignKey(Party, on_delete=models.PROTECT, null=True, blank=True, related_name="sales_orders")
    status     = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)

    # For walk-ins or when customer is not registered
    customer_name    = models.CharField(max_length=255, blank=True, default="")
    customer_phone   = models.CharField(max_length=50,  blank=True, default="")
    customer_address = models.TextField(blank=True, default="")

    # money
    total_amount     = models.DecimalField(**DECIMAL_12_2, default=Decimal("0.00"))  # subtotal of items
    tax_percent      = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    net_total        = models.DecimalField(**DECIMAL_12_2, default=Decimal("0.00"))

    notes      = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["business", "created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"SO #{self.pk or '—'}"

    # ---- totals
    def recompute_totals(self):
        sub = Decimal("0.00")
        for it in self.items.all():
            q = it.quantity or Decimal("0")
            p = it.unit_price or Decimal("0")
            sub += (q * p)
        self.total_amount = _money_q(sub)

        tax  = (self.tax_percent or Decimal("0")) / Decimal("100")
        disc = (self.discount_percent or Decimal("0")) / Decimal("100")
        tax_amt  = _money_q(self.total_amount * tax)
        disc_amt = _money_q(self.total_amount * disc)
        self.net_total = _money_q(self.total_amount + tax_amt - disc_amt)

    @property
    def paid_total(self):
        agg = self.receipt_applications.aggregate(s=Sum("amount"))
        return agg["s"] or Decimal("0.00")

    @property
    def balance_due(self):
        return _money_q((self.net_total or Decimal("0.00")) - self.paid_total)

    def apply_receipt(self, payment: "Payment", amount: Decimal):
        """
        Apply a Payment.IN receipt against this Sales Order (retail).
        """
        app, _ = SalesOrderReceipt.objects.get_or_create(
            sales_order=self, payment=payment,
            defaults={"amount": Decimal("0.00"), "created_by": payment.created_by, "updated_by": payment.updated_by},
        )
        app.amount = _money_q(app.amount + (amount or Decimal("0.00")))
        app.full_clean()
        app.save()
        return app

class SalesOrderItem(models.Model):
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="items")
    product     = models.ForeignKey(Product, on_delete=models.PROTECT)
    
    # NEW: Store which unit was used (Bag or KG)
    uom = models.ForeignKey(
        UnitOfMeasure, 
        on_delete=models.PROTECT, 
        null=True,
        blank=True,
        help_text="Unit used for this line item"
    )
    
    # NEW: Store the multiplier (e.g. 50.00 for a 50kg bag)
    size_per_unit = models.DecimalField(
        max_digits=18, 
        decimal_places=6, 
        default=Decimal("1.000000"),
        help_text="Multiplier to convert to base unit"
    )
    
    quantity    = models.DecimalField(**DECIMAL_18_6, validators=[MinValueValidator(0)])
    unit_price  = models.DecimalField(**DECIMAL_12_2)
    
    # NEW: Snapshot of cost at time of sale
    unit_cost   = models.DecimalField(**DECIMAL_12_2, default=Decimal("0.00"), help_text="Landed cost at time of sale")

    class Meta:
        ordering = ["id"]

    def line_total(self) -> Decimal:
        return (self.quantity or Decimal("0")) * (self.unit_price or Decimal("0"))

    def save(self, *args, **kwargs):
        if not self.unit_cost or self.unit_cost == Decimal("0.00"):
            self.unit_cost = self.product.purchase_price or Decimal("0.00")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity or 0} x {getattr(self.product,'name','—')}"

class SalesOrderReceipt(TimeStampedBy):
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="receipt_applications")
    payment     = models.ForeignKey("Payment", on_delete=models.CASCADE, related_name="applied_sales_orders")
    amount      = models.DecimalField(**DECIMAL_12_2, validators=[MinValueValidator(0)])

    class Meta:
        unique_together = [("sales_order", "payment")]
        indexes = [models.Index(fields=["sales_order"]), models.Index(fields=["payment"])]

    def __str__(self):
        return f"SO#{self.sales_order_id} ⇄ Pay#{self.payment_id} — {self.amount}"

    def _old_amount(self):
        if self.pk:
            try:
                return SalesOrderReceipt.objects.only("amount").get(pk=self.pk).amount
            except SalesOrderReceipt.DoesNotExist:
                pass
        return Decimal("0.00")

    def clean(self):
        if self.amount and self.amount <= 0:
            raise ValidationError("Applied amount must be positive.")
        if self.payment.direction != Payment.IN:
            raise ValidationError("Only IN (receipts) can be applied to Sales Orders.")
        if self.payment.business_id != self.sales_order.business_id:
            raise ValidationError("Payment and Sales Order must belong to same business.")
        reuse = self._old_amount()
        if self.amount > self.payment.remaining_unapplied + reuse:
            raise ValidationError("Applied amount exceeds payment remaining.")
        if self.amount > self.sales_order.balance_due + reuse:
            raise ValidationError("Applied amount exceeds order balance.")



# ----------------------------
# SALES INVOICE
# ----------------------------


class SalesInvoice(TimeStampedBy):
    class Status(models.TextChoices):
        DRAFT   = "draft",   "Draft"
        POSTED  = "posted",  "Posted"
        VOID    = "void",    "Void"

    business = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="sales_invoices")
    customer = models.ForeignKey(Party, on_delete=models.PROTECT, null=True, blank=True, related_name="sales_invoices")

    # Anonymous customer fields (for unregistered customers)
    customer_name    = models.CharField(max_length=255, blank=True, default="")
    customer_phone   = models.CharField(max_length=50,  blank=True, default="")
    customer_address = models.TextField(blank=True, default="")

    status     = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    invoice_no = models.CharField(max_length=50, db_index=True)

    # money
    total_amount     = models.DecimalField(**DECIMAL_12_2, default=Decimal("0.00"))
    tax_percent      = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    net_total        = models.DecimalField(**DECIMAL_12_2, default=Decimal("0.00"))

    notes = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-created_at", "-id"]
        unique_together = [("business", "invoice_no")]
        indexes = [
            models.Index(fields=["business", "invoice_no"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"INV {self.invoice_no or '—'}"

    # ---- totals
    def recompute_totals(self):
        sub = Decimal("0.00")
        for it in self.items.all():
            q = it.quantity or Decimal("0")
            p = it.unit_price or Decimal("0")
            sub += (q * p)
        self.total_amount = _money_q(sub)

        tax  = (self.tax_percent or Decimal("0")) / Decimal("100")
        disc = (self.discount_percent or Decimal("0")) / Decimal("100")
        tax_amt  = _money_q(self.total_amount * tax)
        disc_amt = _money_q(self.total_amount * disc)
        self.net_total = _money_q(self.total_amount + tax_amt - disc_amt)

    # ---- payments/receipts
    @property
    def paid_total(self):
        agg = self.receipt_applications.aggregate(s=Sum("amount"))
        return agg["s"] or Decimal("0.00")

    @property
    def balance_due(self):
        return _money_q((self.net_total or Decimal("0.00")) - self.paid_total)

    def apply_receipt(self, payment: "Payment", amount: Decimal):
        app, _ = SalesInvoiceReceipt.objects.get_or_create(
            sales_invoice=self, payment=payment,
            defaults={"amount": Decimal("0.00"), "created_by": payment.created_by, "updated_by": payment.updated_by},
        )
        app.amount = _money_q(app.amount + (amount or Decimal("0.00")))
        app.full_clean()
        app.save()
        return app

    # ---- stock posting
    def _is_posted(self) -> bool:
        return (self.status or "").lower() == "posted"

    @transaction.atomic
    def save(self, *args, **kwargs):
        creating = self.pk is None
        if not self.invoice_no:
            # assign once
            self.invoice_no = _next_invoice_no(self.business)
        super().save(*args, **kwargs)

        # Post stock only when POSTED; we adjust via items (delta safe)

class SalesInvoiceItem(models.Model):
    sales_invoice = models.ForeignKey(SalesInvoice, on_delete=models.CASCADE, related_name="items")
    product       = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity      = models.DecimalField(**DECIMAL_18_6, validators=[MinValueValidator(0)])
    unit_price    = models.DecimalField(**DECIMAL_12_2)

    class Meta:
        ordering = ["id"]

    def line_total(self) -> Decimal:
        return (self.quantity or Decimal("0")) * (self.unit_price or Decimal("0"))

    def __str__(self):
        return f"{self.quantity or 0} x {getattr(self.product,'name','—')}"

    # ---- STOCK OUT when invoice is POSTED
    def _is_posted(self) -> bool:
        try:
            return (self.sales_invoice.status or "").lower() == "posted"
        except Exception:
            return False

    @staticmethod
    def _add_stock(product_id, delta: Decimal):
        if not delta:
            return
        (Product.objects
         .select_for_update()
         .filter(pk=product_id)
         .update(stock_qty=F("stock_qty") + delta))

    @transaction.atomic
    def save(self, *args, **kwargs):
        creating = self.pk is None
        old_product_id = None
        old_qty = Decimal("0")
        if not creating:
            prev = (SalesInvoiceItem.objects
                    .select_for_update()
                    .only("product_id", "quantity")
                    .get(pk=self.pk))
            old_product_id = prev.product_id
            old_qty = prev.quantity or Decimal("0")

        super().save(*args, **kwargs)

        if not self._is_posted():
            return

        new_product_id = self.product_id
        new_qty = self.quantity or Decimal("0")

        if creating:
            # invoice posted -> stock OUT
            self._add_stock(new_product_id, -new_qty)
        else:
            if old_product_id != new_product_id:
                if old_product_id:
                    self._add_stock(old_product_id, +old_qty)   # undo old OUT
                if new_product_id:
                    self._add_stock(new_product_id, -new_qty)   # apply new OUT
            else:
                delta = new_qty - old_qty
                if delta:
                    self._add_stock(new_product_id, -delta)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        if self._is_posted() and self.product_id and self.quantity:
            (Product.objects
             .select_for_update()
             .filter(pk=self.product_id)
             .update(stock_qty=F("stock_qty") + (self.quantity or Decimal("0"))))
        super().delete(*args, **kwargs)

# Bridge: Sales Invoice ↔️ Receipt (Payment.IN)
class SalesInvoiceReceipt(TimeStampedBy):
    sales_invoice = models.ForeignKey(SalesInvoice, on_delete=models.CASCADE, related_name="receipt_applications")
    payment       = models.ForeignKey("Payment", on_delete=models.CASCADE, related_name="applied_sales_invoices")
    amount        = models.DecimalField(**DECIMAL_12_2, validators=[MinValueValidator(0)])

    class Meta:
        unique_together = [("sales_invoice", "payment")]
        indexes = [models.Index(fields=["sales_invoice"]), models.Index(fields=["payment"])]

    def __str__(self):
        return f"INV#{self.sales_invoice_id} ⇄ Pay#{self.payment_id} — {self.amount}"

    def _old_amount(self):
        if self.pk:
            try:
                return SalesInvoiceReceipt.objects.only("amount").get(pk=self.pk).amount
            except SalesInvoiceReceipt.DoesNotExist:
                pass
        return Decimal("0.00")

    def clean(self):
        if self.amount and self.amount <= 0:
            raise ValidationError("Applied amount must be positive.")
        if self.payment.direction != Payment.IN:
            raise ValidationError("Only IN (receipts) can be applied to Invoices.")
        if self.payment.business_id != self.sales_invoice.business_id:
            raise ValidationError("Payment and Sales Invoice must belong to same business.")
        reuse = self._old_amount()
        if self.amount > self.payment.remaining_unapplied + reuse:
            raise ValidationError("Applied amount exceeds payment remaining.")
        if self.amount > self.sales_invoice.balance_due + reuse:
            raise ValidationError("Applied amount exceeds invoice balance.")

# ----------------------------
# SALES RETURN
# ----------------------------

class SalesReturn(TimeStampedBy):
    class Status(models.TextChoices):
        PENDING   = "pending",   "Pending"
        PROCESSED = "processed", "Processed"

    business = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="sales_returns")
    customer = models.ForeignKey(Party, on_delete=models.PROTECT, null=True, blank=True, related_name="sales_returns")
    # Optionally link to original invoice (for convenience)
    source_invoice = models.ForeignKey("SalesInvoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="returns")
    # Link to original sales order (primary way to create returns)
    source_order = models.ForeignKey("SalesOrder", on_delete=models.SET_NULL, null=True, blank=True, related_name="returns")

    # anonymous customer (if no Party)
    customer_name    = models.CharField(max_length=255, blank=True, default="")
    customer_phone   = models.CharField(max_length=50,  blank=True, default="")
    customer_address = models.TextField(blank=True, default="")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    # money
    total_amount     = models.DecimalField(**DECIMAL_12_2, default=Decimal("0.00"))
    tax_percent      = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    net_total        = models.DecimalField(**DECIMAL_12_2, default=Decimal("0.00"))

    notes = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"SR #{self.pk or '—'}"

    # totals
    def recompute_totals(self):
        sub = Decimal("0.00")
        for it in self.items.all():
            q = it.quantity or Decimal("0")
            p = it.unit_price or Decimal("0")
            sub += (q * p)
        self.total_amount = _money_q(sub)

        tax  = (self.tax_percent or Decimal("0")) / Decimal("100")
        disc = (self.discount_percent or Decimal("0")) / Decimal("100")
        tax_amt  = _money_q(self.total_amount * tax)
        disc_amt = _money_q(self.total_amount * disc)
        self.net_total = _money_q(self.total_amount + tax_amt - disc_amt)

    @property
    def refunded_total(self):
        agg = self.refund_applications.aggregate(s=Sum("amount"))
        return agg["s"] or Decimal("0.00")

    @property
    def refund_remaining(self):
        return _money_q((self.net_total or Decimal("0.00")) - self.refunded_total)

    def apply_refund(self, payment: "Payment", amount: Decimal):
        app, _ = SalesReturnRefund.objects.get_or_create(
            sales_return=self, payment=payment,
            defaults={"amount": Decimal("0.00"), "created_by": payment.created_by, "updated_by": payment.updated_by},
        )
        app.amount = _money_q(app.amount + (amount or Decimal("0.00")))
        app.full_clean()
        app.save()
        return app

class SalesReturnItem(models.Model):
    sales_return = models.ForeignKey(SalesReturn, on_delete=models.CASCADE, related_name="items")
    product      = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity     = models.DecimalField(**DECIMAL_18_6, validators=[MinValueValidator(0)])
    unit_price   = models.DecimalField(**DECIMAL_12_2)

    class Meta:
        ordering = ["id"]

    def line_total(self) -> Decimal:
        return (self.quantity or Decimal("0")) * (self.unit_price or Decimal("0"))

    def __str__(self):
        return f"{self.quantity or 0} x {getattr(self.product,'name','—')}"

    # STOCK IN when return is processed
    def _is_processed(self) -> bool:
        try:
            return (self.sales_return.status or "").lower() == "processed"
        except Exception:
            return False

    @staticmethod
    def _add_stock(product_id, delta: Decimal):
        if not delta:
            return
        (Product.objects
         .select_for_update()
         .filter(pk=product_id)
         .update(stock_qty=F("stock_qty") + delta))

    @transaction.atomic
    def save(self, *args, **kwargs):
        creating = self.pk is None
        old_product_id = None
        old_qty = Decimal("0")
        if not creating:
            prev = (SalesReturnItem.objects
                    .select_for_update()
                    .only("product_id", "quantity")
                    .get(pk=self.pk))
            old_product_id = prev.product_id
            old_qty = prev.quantity or Decimal("0")

        super().save(*args, **kwargs)

        if not self._is_processed():
            return

        new_product_id = self.product_id
        new_qty = self.quantity or Decimal("0")

        if creating:
            # processed return -> stock IN
            self._add_stock(new_product_id, +new_qty)
        else:
            if old_product_id != new_product_id:
                if old_product_id:
                    self._add_stock(old_product_id, -old_qty)  # undo old IN
                if new_product_id:
                    self._add_stock(new_product_id, +new_qty)  # apply new IN
            else:
                delta = new_qty - old_qty
                if delta:
                    self._add_stock(new_product_id, +delta)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        if self._is_processed() and self.product_id and self.quantity:
            (Product.objects
             .select_for_update()
             .filter(pk=self.product_id)
             .update(stock_qty=F("stock_qty") - (self.quantity or Decimal("0"))))
        super().delete(*args, **kwargs)

# Bridge: Sales Return ↔️ Refund (Payment.OUT)
class SalesReturnRefund(TimeStampedBy):
    sales_return = models.ForeignKey(SalesReturn, on_delete=models.CASCADE, related_name="refund_applications")
    payment      = models.ForeignKey("Payment", on_delete=models.CASCADE, related_name="applied_sales_returns")
    amount       = models.DecimalField(**DECIMAL_12_2, validators=[MinValueValidator(0)])

    class Meta:
        unique_together = [("sales_return", "payment")]
        indexes = [models.Index(fields=["sales_return"]), models.Index(fields=["payment"])]

    def __str__(self):
        return f"SR#{self.sales_return_id} ⇄ Pay#{self.payment_id} — {self.amount}"

    def _old_amount(self):
        if self.pk:
            try:
                return SalesReturnRefund.objects.only("amount").get(pk=self.pk).amount
            except SalesReturnRefund.DoesNotExist:
                pass
        return Decimal("0.00")

    def clean(self):
        if self.amount and self.amount <= 0:
            raise ValidationError("Applied amount must be positive.")
        if self.payment.direction != Payment.OUT:
            raise ValidationError("Only OUT (refund) payments can be applied to Sales Returns.")
        if self.payment.business_id != self.sales_return.business_id:
            raise ValidationError("Payment and Sales Return must belong to same business.")
        reuse = self._old_amount()
        if self.amount > self.payment.remaining_unapplied + reuse:
            raise ValidationError("Applied amount exceeds payment remaining.")
        if self.amount > self.sales_return.refund_remaining + reuse:
            raise ValidationError("Applied amount exceeds return balance.")


#--------------
#   Warehouse
#--------------

# Existing models in your project:
# from .models import Business, Product, TimeStampedBy, User

class Warehouse(TimeStampedBy):
    """
    Physical storage that can hold products from any business.
    """
    name      = models.CharField(max_length=200, unique=True)
    code      = models.CharField(max_length=50, unique=True)
    address   = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return f"{self.code} — {self.name}"

class WarehouseStock(TimeStampedBy):
    """
    Per-warehouse, per-product quantity.
    One row per (warehouse, product). Quantity tracks on-hand units.
    """
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="stocks")
    product   = models.ForeignKey("Product", on_delete=models.PROTECT, related_name="warehouse_stocks")
    quantity  = models.DecimalField(**DECIMAL_18_6, validators=[MinValueValidator(0)], default=Decimal("0"))

    class Meta:
        unique_together = [("warehouse", "product")]
        indexes = [
            models.Index(fields=["warehouse", "product"]),
        ]

    def __str__(self):
        return f"[WH {self.warehouse.code}] {getattr(self.product, 'name', '—')} = {self.quantity}"

class BusinessStock(TimeStampedBy):
    """
    Per-business, per-product quantity visible to POS/sales.
    If you already track business level stock elsewhere, map to that and skip this model.
    """
    business = models.ForeignKey("Business", on_delete=models.CASCADE, related_name="stocks")
    product  = models.ForeignKey("Product", on_delete=models.PROTECT, related_name="business_stocks")
    quantity = models.DecimalField(**DECIMAL_18_6, validators=[MinValueValidator(0)], default=Decimal("0"))

    class Meta:
        unique_together = [("business", "product")]
        indexes = [
            models.Index(fields=["business", "product"]),
        ]

    def __str__(self):
        return f"[{self.business.name}] {getattr(self.product,'name','—')} = {self.quantity}"

class StockMove(TimeStampedBy):
    class Status(models.TextChoices):
        DRAFT  = "draft", "Draft"
        POSTED = "posted", "Posted"

    product = models.ForeignKey("Product", on_delete=models.PROTECT)

    # Source
    source_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, null=True, blank=True, related_name="out_moves"
    )
    source_business  = models.ForeignKey(
        "Business", on_delete=models.PROTECT, null=True, blank=True, related_name="out_moves"
    )

    # Destination
    dest_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, null=True, blank=True, related_name="in_moves"
    )
    dest_business  = models.ForeignKey(
        "Business", on_delete=models.PROTECT, null=True, blank=True, related_name="in_moves"
    )

    quantity = models.DecimalField(**DECIMAL_18_6, validators=[MinValueValidator(Decimal("0.000001"))])
    status   = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)

    reference = models.CharField(max_length=120, blank=True, default="")
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["product"]),
        ]

    def __str__(self):
        return f"Move#{self.pk or '—'} {self.quantity} x {getattr(self.product,'name','—')}"

    # ---- helpers

    def _one_source_one_dest(self):
        src = [self.source_warehouse, self.source_business]
        dst = [self.dest_warehouse, self.dest_business]
        if sum(1 for x in src if x) != 1 or sum(1 for x in dst if x) != 1:
            raise ValidationError("Provide exactly one source and one destination.")

    def _stock_row(self, *, warehouse=None, business=None):
        """
        Fetch or create the correct stock row for a product for the given location.
        """
        if warehouse:
            obj, _ = WarehouseStock.objects.get_or_create(
                warehouse=warehouse, product=self.product,
                defaults={"quantity": Decimal("0")}
            )
            return obj
        if business:
            obj, _ = BusinessStock.objects.get_or_create(
                business=business, product=self.product,
                defaults={"quantity": Decimal("0")}
            )
            return obj
        raise ValidationError("Invalid stock location.")

    def clean(self):
        self._one_source_one_dest()

        if self.quantity is None or self.quantity <= 0:
            raise ValidationError("Quantity must be positive.")

        # Business <-> Warehouse must respect product.business
        # product.business must match the side that is a Business.
        prod_business_id = getattr(self.product, "business_id", None)

        if self.source_business and self.source_business_id != prod_business_id:
            raise ValidationError("Product's business must match source business.")
        if self.dest_business and self.dest_business_id != prod_business_id:
            raise ValidationError("Product's business must match destination business.")

        # No same-to-same
        if self.source_warehouse_id and self.dest_warehouse_id and self.source_warehouse_id == self.dest_warehouse_id:
            raise ValidationError("Source and destination warehouse cannot be the same.")
        if self.source_business_id and self.dest_business_id and self.source_business_id == self.dest_business_id:
            raise ValidationError("Source and destination business cannot be the same.")

        # If posting now, make sure source has enough
        if self.status == self.Status.POSTED and self.pk:
            # Skip for now; we validate again in post()
            pass

    @transaction.atomic
    def post(self, user=None):
        if self.status == self.Status.POSTED:
            raise ValidationError("Move already posted.")

        self.full_clean()

        # Ensure PK exists before side-effects
        if not self.pk:
            super().save()

        # Source stock row
        if self.source_warehouse_id:
            src = self._stock_row(warehouse=self.source_warehouse)
        else:
            src = self._stock_row(business=self.source_business)

        if src.quantity < self.quantity:
            raise ValidationError("Insufficient source stock to post this move.")

        # Destination stock row
        if self.dest_warehouse_id:
            dst = self._stock_row(warehouse=self.dest_warehouse)
        else:
            dst = self._stock_row(business=self.dest_business)

        # Apply row-level quantities
        src.quantity = (src.quantity or Decimal("0")) - self.quantity
        dst.quantity = (dst.quantity or Decimal("0")) + self.quantity
        src.full_clean(); dst.full_clean()
        src.save(update_fields=["quantity", "updated_at"])
        dst.save(update_fields=["quantity", "updated_at"])

        # >>> NEW: reflect on Product.stock_qty when a Business is involved <<<
        # - WH -> Business: add to product.stock_qty
        # - Business -> WH: subtract from product.stock_qty (when you enable that direction)
        delta = Decimal("0")
        if self.dest_business_id:
            delta += self.quantity
        if self.source_business_id:
            delta -= self.quantity
        if delta:
            (Product.objects
             .select_for_update()
             .filter(pk=self.product_id)
             .update(stock_qty=F("stock_qty") + delta))
        # <<< END NEW >>>

        self.status = self.Status.POSTED
        self.posted_at = timezone.now()
        if user and not self.updated_by_id:
            self.updated_by = user
        self.save(update_fields=["status", "posted_at", "updated_by", "updated_at"])
        return self


# --------------------------------
# User Settings
# --------------------------------
class UserSettings(models.Model):
    """User-specific settings like barcode printer preferences."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="settings",
    )
    business_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Business name to display on barcode labels"
    )
    barcode_printer_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Barcode label printer name (e.g., BC-LP1300)"
    )
    DEFAULT_SALE_PAYMENT_CASH = "cash"
    DEFAULT_SALE_PAYMENT_ON_CREDIT = "on_credit"
    DEFAULT_SALE_PAYMENT_CHOICES = [
        (DEFAULT_SALE_PAYMENT_CASH, "Cash"),
        (DEFAULT_SALE_PAYMENT_ON_CREDIT, "On Credit"),
    ]
    default_sale_payment_method = models.CharField(
        max_length=20,
        choices=DEFAULT_SALE_PAYMENT_CHOICES,
        default=DEFAULT_SALE_PAYMENT_CASH,
        help_text="Default payment method in Sale Order (Cash or On Credit)",
    )
    default_sale_business = models.ForeignKey(
        "Business",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_users",
        help_text="Default business to auto-select when creating a new Sale Order",
    )
    
    # Granular Password Protection Permissions
    protect_receivables = models.BooleanField(default=False, help_text="Require password to view Total Receivables")
    protect_payables = models.BooleanField(default=False, help_text="Require password to view Total Payables")
    protect_cash_in_hand = models.BooleanField(default=False, help_text="Require password to view Cash in Hand")
    protect_inventory = models.BooleanField(default=False, help_text="Require password to view Total Inventory Value")

    cancellation_password = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Hashed password required to cancel a sale order. Set/change in User Settings. Not your login password.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "User Settings"
        verbose_name_plural = "User Settings"
    
    def __str__(self):
        return f"Settings for {self.user.username}"
