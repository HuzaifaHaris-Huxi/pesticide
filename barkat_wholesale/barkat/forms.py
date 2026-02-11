

from decimal import Decimal, InvalidOperation

# ===============================
# Django
# ===============================

from decimal import Decimal
from django import forms
from django.db.models import Q

from .models import (
    PurchaseOrder,
    PurchaseOrderItem,
    Party,
    BankAccount,
    Warehouse,          # <-- make sure this is imported
    Product,
    Business,
    UserSettings,
)

from django import forms
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.forms import inlineformset_factory, BaseInlineFormSet
from django.utils import timezone

# ===============================
# Local App Models
# ===============================
from .models import (
    Business,
    Party,
    Staff,
    BankAccount,
    BankMovement,
    CashFlow,
    Product,
    ProductCategory,
    ProductImage,
    UnitOfMeasure,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderPayment,
    PurchaseReturn,
    PurchaseReturnItem,
    PurchaseReturnRefund,
    SalesOrder,
    SalesOrderItem,
    SalesInvoice,
    SalesInvoiceItem,
    SalesInvoiceReceipt,
    SalesReturn,
    SalesReturnItem,
    SalesReturnRefund,
    Expense,
    ExpenseCategory,
    Payment,
    StockTransaction,
)
BASE_INPUT = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2"

class BusinessForm(forms.ModelForm):
    class Meta:
        model = Business
        fields = [
            "code", "name", "legal_name", "ntn", "sales_tax_reg",
            "phone", "email", "address", "pos_printer_name", "is_active"
        ]
        widgets = {
            "code": forms.TextInput(attrs={"class": BASE_INPUT}),
            "name": forms.TextInput(attrs={"class": BASE_INPUT}),
            "legal_name": forms.TextInput(attrs={"class": BASE_INPUT}),
            "ntn": forms.TextInput(attrs={"class": BASE_INPUT}),
            "sales_tax_reg": forms.TextInput(attrs={"class": BASE_INPUT}),
            "phone": forms.TextInput(attrs={"class": BASE_INPUT}),
            "email": forms.EmailInput(attrs={"class": BASE_INPUT}),
            "address": forms.Textarea(attrs={"class": BASE_INPUT, "rows": 3}),
            "pos_printer_name": forms.TextInput(attrs={
                "class": BASE_INPUT,
                "placeholder": "POS80 Printer name (e.g., EPSON_TM_T20)"
            }),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-600"}),
        }

class PartyForm(forms.ModelForm):
    class Meta:
        model = Party
        fields = [
            "type",
            "display_name",
            "legal_name",
            "phone",
            "email",
            "address",
            "gst_number",
            "opening_balance",
            "opening_balance_side",
            "opening_balance_date",
            "default_business",
            "is_active",
        ]
        widgets = {
            "type": forms.Select(attrs={"class": BASE_INPUT}),
            "display_name": forms.TextInput(attrs={"class": BASE_INPUT}),
            "legal_name": forms.TextInput(attrs={"class": BASE_INPUT}),
            "phone": forms.TextInput(attrs={"class": BASE_INPUT}),
            "email": forms.EmailInput(attrs={"class": BASE_INPUT}),
            "address": forms.Textarea(attrs={"class": BASE_INPUT, "rows": 3}),
            "gst_number": forms.TextInput(attrs={"class": BASE_INPUT}),
            "opening_balance": forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
            "opening_balance_side": forms.RadioSelect(attrs={"class": "flex gap-4"}),
            "opening_balance_date": forms.DateInput(attrs={"type": "date", "class": BASE_INPUT}),
            "default_business": forms.Select(attrs={"class": BASE_INPUT}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-600"}),
        }

    def __init__(self, *args, **kwargs):
        # fixed_type will be passed only from create view
        self.fixed_type = kwargs.pop("fixed_type", None)
        super().__init__(*args, **kwargs)

        if self.fixed_type is not None:
            # show chosen type but lock it
            self.fields["type"].initial = self.fixed_type
            self.fields["type"].disabled = True
            # optional. helps some browsers
            self.fields["type"].widget.attrs["readonly"] = True

        # Auto-fill opening_balance_date with today's date for new parties
        if not self.instance.pk:
            from django.utils import timezone
            self.fields["opening_balance_date"].initial = timezone.now().date()

    def clean_opening_balance(self):
        val = self.cleaned_data.get("opening_balance")
        if val is not None and val < 0:
            raise forms.ValidationError("Opening balance cannot be negative.")
        return val

class ProductCategoryForm(forms.ModelForm):
    class Meta:
        model = ProductCategory
        fields = ["business", "parent", "name", "code"]
        widgets = {
            "business": forms.Select(attrs={"class": BASE_INPUT}),
            "parent":   forms.Select(attrs={"class": BASE_INPUT}),
            "name":     forms.TextInput(attrs={"class": BASE_INPUT}),
            "code":     forms.TextInput(attrs={"class": BASE_INPUT}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Make parent labels show the category NAME (optionally include code)
        self.fields["parent"].label_from_instance = lambda obj: f"{obj.name}"

        # Show an empty "---" choice (parent is optional)
        self.fields["parent"].empty_label = "— No parent —"

        # Resolve the business to scope parent queryset
        business = None
        if self.is_bound:
            # Prefer POSTed value while creating/updating
            b = self.data.get("business")
            try:
                business_id = int(b) if b not in (None, "", "None") else None
            except (TypeError, ValueError):
                business_id = None
            if business_id:
                business = Business.objects.filter(pk=business_id, is_deleted=False).first()
        elif self.instance and self.instance.pk:
            # Editing: use the instance's business
            business = self.instance.business
        else:
            # Creating and not bound: try initial
            b = self.initial.get("business")
            if b:
                business = Business.objects.filter(pk=b).first() if not isinstance(b, Business) else b

        # Base queryset: only same business (if known), not deleted
        qs = ProductCategory.objects.filter(is_deleted=False)
        if business:
            qs = qs.filter(business=business)

        # Exclude self from parent choices (when editing)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        self.fields["parent"].queryset = qs.order_by("name")

    # --- Validation helpers ---

    def _is_descendant_of(self, candidate_parent: ProductCategory, node: ProductCategory) -> bool:
        """
        Return True if candidate_parent is a descendant of node.
        Walks up the parent chain from candidate_parent.
        """
        seen = set()
        cur = candidate_parent
        while cur and cur.pk and cur.pk not in seen:
            if cur.pk == node.pk:
                return True
            seen.add(cur.pk)
            cur = cur.parent
        return False

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")
        business = self.cleaned_data.get("business") or getattr(self.instance, "business", None)

        if not parent:
            return parent

        # Same-business guard
        if business and parent.business_id != business.id:
            raise forms.ValidationError("Parent must belong to the same business.")

        # Self/descendant guard (when editing existing)
        if self.instance and self.instance.pk:
            if parent.pk == self.instance.pk:
                raise forms.ValidationError("A category cannot be its own parent.")
            if self._is_descendant_of(parent, self.instance):
                raise forms.ValidationError("Cannot set a descendant as parent (would create a cycle).")

        return parent

    def clean_code(self):
        code = self.cleaned_data.get("code")
        if code:
            code = code.strip()
            return code if code else None
        return None
    
class CategoryChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        # Show just the category name:
        return obj.name
        # Or, if you prefer: return f"{obj.business.name} — {obj.name}"

class ProductForm(forms.ModelForm):
    current_stock = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=18, decimal_places=6,
        widget=forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.000001"}),
        label="Current stock",
        help_text="Opening/adjusted quantity in the product's base UoM.",
    )

    class Meta:
        model = Product
        fields = [
            "business", "category", "name", "company_name", "sku", "barcode", 
            "uom", "bulk_uom", "default_bulk_size", 
            "purchase_price", "sale_price", "min_stock",
            "is_serialized", "has_expiry",
        ]
        widgets = {
            "business":          forms.Select(attrs={"class": BASE_INPUT}),
            "category":          forms.Select(attrs={"class": BASE_INPUT}),
            "name":              forms.TextInput(attrs={"class": BASE_INPUT}),
            "company_name":      forms.TextInput(attrs={"class": BASE_INPUT, "placeholder": "e.g., Lays, Coca-Cola"}),
            "sku":               forms.TextInput(attrs={"class": BASE_INPUT}),
            "barcode":           forms.TextInput(attrs={"class": BASE_INPUT}),
            "uom":               forms.Select(attrs={"class": BASE_INPUT}),
            "bulk_uom":          forms.Select(attrs={"class": BASE_INPUT}), 
            "default_bulk_size": forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.000001"}), 
            "purchase_price":    forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
            "sale_price":        forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
            "min_stock":         forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.000001"}),
            "is_serialized":     forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-600"}),
            "has_expiry":        forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-600"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ---------- UOM & Bulk UOM nice labels ----------
        uom_qs = UnitOfMeasure.objects.all().order_by("code")
        self.fields["uom"].queryset = uom_qs
        self.fields["uom"].empty_label = "Select base unit"
        
        self.fields["bulk_uom"].queryset = uom_qs
        self.fields["bulk_uom"].empty_label = "Select bulk unit (Optional)"

        def uom_label(u):
            name = getattr(u, "name", "") or ""
            sym  = getattr(u, "symbol", "") or ""
            if name and sym: return f"{name} ({u.code}, {sym})"
            if name: return f"{name} ({u.code})"
            return u.code

        self.fields["uom"].label_from_instance = uom_label
        self.fields["bulk_uom"].label_from_instance = uom_label

        # ---------- Category filtered by Business ----------
        business = None
        if self.is_bound:
            bid = self.data.get("business")
            if bid and str(bid).isdigit():
                business = Business.objects.filter(pk=int(bid), is_deleted=False).first()
        if not business and self.instance and self.instance.pk:
            business = self.instance.business
        if not business:
            bid = self.initial.get("business")
            if bid and str(bid).isdigit():
                business = Business.objects.filter(pk=int(bid), is_deleted=False).first()

        if business:
            cat_qs = ProductCategory.objects.filter(is_deleted=False, business=business).order_by("name")
        else:
            cat_qs = ProductCategory.objects.none()

        self.fields["category"].queryset = cat_qs
        self.fields["category"].empty_label = "Select category"
        
        # FIX: Show ONLY the category name instead of the business/code path
        self.fields["category"].label_from_instance = lambda obj: f"{obj.name}"

    def clean_barcode(self):
        barcode = self.cleaned_data.get("barcode", "").strip()
        business = self.cleaned_data.get("business")
        
        # If barcode is empty, that's OK (it will be auto-generated)
        if not barcode:
            return barcode
        
        # Get the current product's business (from form data or instance)
        if not business:
            if self.instance and self.instance.pk:
                business = self.instance.business
            else:
                # Try to get from form data
                bid = self.data.get("business")
                if bid and str(bid).isdigit():
                    business = Business.objects.filter(pk=int(bid)).first()
        
        # Check if barcode already exists in OTHER businesses
        existing_product = Product.objects.filter(
            barcode=barcode
        ).exclude(
            barcode=""  # Exclude empty barcodes
        )
        
        # If editing existing product, exclude itself
        if self.instance and self.instance.pk:
            existing_product = existing_product.exclude(pk=self.instance.pk)
        
        # Check if barcode exists in any other business
        if business:
            existing_in_other_business = existing_product.exclude(business=business).first()
            if existing_in_other_business:
                other_business_name = existing_in_other_business.business.name
                product_name = existing_in_other_business.name
                raise forms.ValidationError(
                    f"This barcode already exists in another business '{other_business_name}' "
                    f"for product '{product_name}'. Please use a different barcode or contact the administrator."
                )
        else:
            # No business selected yet, but check if barcode exists anywhere
            if existing_product.exists():
                first_existing = existing_product.first()
                other_business_name = first_existing.business.name
                product_name = first_existing.name
                raise forms.ValidationError(
                    f"This barcode already exists in business '{other_business_name}' "
                    f"for product '{product_name}'. Please use a different barcode or contact the administrator."
                )
        
        return barcode

        # ---------- Prefill current_stock ----------
        if self.instance and self.instance.pk:
            self.fields["current_stock"].initial = self.instance.stock_qty or Decimal("0")

    def clean(self):
        cleaned = super().clean()
        dbs = cleaned.get("default_bulk_size")
        if dbs is not None and dbs <= 0:
            self.add_error("default_bulk_size", "Bulk size must be greater than zero.")
        return cleaned

    def save(self, commit=True):
        product = super().save(commit=False)
        cs = self.cleaned_data.get("current_stock")
        if cs is not None:
            product.stock_qty = cs
        if commit:
            product.save()
            self.save_m2m()
        return product


# ---------- ProductImage inline formset (image optional) ----------

class ProductImageForm(forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ["image", "alt_text", "is_primary", "sort_order"]
        widgets = {
            "image":      forms.ClearableFileInput(attrs={
                "class": "w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
            }),
            "alt_text":   forms.TextInput(attrs={
                "class": "w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
            }),
            "is_primary": forms.CheckboxInput(attrs={
                "class": "h-4 w-4 rounded border-slate-600"
            }),
            "sort_order": forms.NumberInput(attrs={
                "class": "w-full rounded-lg border border-slate-300 bg-white px-3 py-2",
                "min": 0, "step": 1
            }),
        }

    def clean(self):
        cleaned = super().clean()

        # If this form is marked for deletion, skip further checks
        if getattr(self, "can_delete", False) and cleaned.get("DELETE"):
            return cleaned

        img_field     = cleaned.get("image")
        is_primary    = cleaned.get("is_primary")
        instance_file = getattr(self.instance, "image", None)

        # Require a file only if Primary is checked and no existing file
        if is_primary:
            if not img_field and not (instance_file and instance_file.name):
                self.add_error("image", "Primary image must have a file.")

        # Everything else is optional:
        # - Alt text without a file is allowed.
        # - Sort order without a file is allowed.
        return cleaned

class _ProductImageBaseFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()

        # Count primaries only among non-deleted forms that end up having a file
        primaries = []
        any_real_image = False

        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if self.can_delete and form.cleaned_data.get("DELETE"):
                continue

            is_primary = form.cleaned_data.get("is_primary", False)

            # Does this row have a file either newly uploaded or already present?
            has_file_now = bool(form.cleaned_data.get("image"))
            has_file_existing = bool(getattr(form.instance.image, "name", ""))

            row_has_image = has_file_now or has_file_existing
            any_real_image = any_real_image or row_has_image

            if is_primary and row_has_image:
                primaries.append(form)

            # If Primary is checked but there is no file at all, the form-level clean will flag it.

        if len(primaries) > 1:
            raise forms.ValidationError("Only one image can be marked as Primary.")

        # If there are images but none is primary, auto-promote the first image row to primary
        if any_real_image and len(primaries) == 0:
            for form in self.forms:
                if self.can_delete and form.cleaned_data.get("DELETE"):
                    continue
                has_file_now = bool(form.cleaned_data.get("image"))
                has_file_existing = bool(getattr(form.instance.image, "name", ""))
                if has_file_now or has_file_existing:
                    form.cleaned_data["is_primary"] = True
                    break

ProductImageFormSet = inlineformset_factory(
    parent_model=Product,
    model=ProductImage,
    form=ProductImageForm,
    formset=_ProductImageBaseFormSet,
    fields=["image", "alt_text", "is_primary", "sort_order"],
    extra=1,
    can_delete=True,
    max_num=10,
)



from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from .models import Staff

BASE_INPUT_CLS = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2"

class StaffForm(forms.ModelForm):
    # Shown only when access is checked and no existing user is selected
    username  = forms.CharField(required=False, max_length=150)
    email     = forms.EmailField(required=False)
    password1 = forms.CharField(required=False, widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(required=False, widget=forms.PasswordInput, strip=False)

    class Meta:
        model = Staff
        fields = [
            "business",
            "full_name",
            "role",
            "phone",
            "cnic",
            "address",
            "has_software_access",
            "user",  # existing user, optional
            "access_sales",
            "access_inventory",
            "access_accounts",
            "joined_on",
            "salary_start",
            "monthly_salary",
        ]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3, "class": BASE_INPUT}),
            "joined_on": forms.DateInput(attrs={"type": "date", "class": BASE_INPUT}),
            "salary_start": forms.DateInput(attrs={"type": "date", "class": BASE_INPUT}),
            "monthly_salary": forms.NumberInput(attrs={"class": BASE_INPUT}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        text_like = (forms.TextInput, forms.NumberInput, forms.EmailInput, forms.DateInput, forms.URLInput)
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, text_like):
                w.attrs.setdefault("class", BASE_INPUT)
            elif isinstance(w, forms.Select):
                w.attrs.setdefault("class", BASE_INPUT)

        # Extras styling
        self.fields["username"].widget.attrs.setdefault("class", BASE_INPUT)
        self.fields["email"].widget.attrs.setdefault("class", BASE_INPUT)
        self.fields["password1"].widget.attrs.setdefault("class", BASE_INPUT)
        self.fields["password2"].widget.attrs.setdefault("class", BASE_INPUT)

        # Nice placeholders
        self.fields["full_name"].widget.attrs.setdefault("placeholder", "Full name")
        self.fields["phone"].widget.attrs.setdefault("placeholder", "03xx-xxxxxxx")
        self.fields["cnic"].widget.attrs.setdefault("placeholder", "xxxxx-xxxxxxx-x")

    def clean(self):
        cleaned = super().clean()
        User = get_user_model()

        business = cleaned.get("business")
        has_access = cleaned.get("has_software_access")
        existing_user = cleaned.get("user")

        username = (cleaned.get("username") or "").strip()
        email = (cleaned.get("email") or "").strip()
        pw1 = cleaned.get("password1") or ""
        pw2 = cleaned.get("password2") or ""

        if not business:
            raise ValidationError("Please select a Business for this staff member.")

        # If access is enabled and no existing user is chosen, username/password are required
        if has_access and not existing_user:
            if not username or not pw1 or not pw2:
                raise ValidationError("Provide username and password, or select an existing user.")
            if pw1 != pw2:
                raise ValidationError("Passwords do not match.")
            if User.objects.filter(username=username).exists():
                raise ValidationError("Username is already taken.")

        # If access is enabled and existing user selected, ensure it's active
        if has_access and existing_user and not existing_user.is_active:
            raise ValidationError("Linked user is inactive. Activate the user or disable software access.")

        return cleaned

    def save(self, commit=True):
        """
        If access is enabled and no user selected, create a User with the provided
        username/password and link it before saving Staff.
        """
        User = get_user_model()
        obj: Staff = super().save(commit=False)

        has_access = self.cleaned_data.get("has_software_access")
        existing_user = self.cleaned_data.get("user")

        if has_access and not existing_user:
            username = (self.cleaned_data.get("username") or "").strip()
            email = (self.cleaned_data.get("email") or "").strip()
            password = self.cleaned_data.get("password1")

            new_user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
            )
            obj.user = new_user  # link the newly created user

        if commit:
            obj.save()
            self.save_m2m()

        return obj


class UserSettingsForm(forms.ModelForm):
    cancellation_password_old = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            "class": "w-full max-w-xs rounded-lg border border-slate-300 px-3 py-2",
            "placeholder": "Current cancellation password",
            "autocomplete": "off",
        }),
        label="Current cancellation password",
        help_text="Required only when changing or removing an existing password.",
    )
    cancellation_password_new = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            "class": "w-full max-w-xs rounded-lg border border-slate-300 px-3 py-2",
            "placeholder": "New cancellation password",
            "autocomplete": "new-password",
        }),
        label="New cancellation password",
        help_text="Leave blank to keep current. Set to require password for: order cancel, supplier ledger, party-balances suppliers.",
    )
    remove_cancellation_password = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-300"}),
        label="Remove cancellation password",
        help_text="Check to clear the password. Then no password is required for cancel, supplier ledger, or party-balances.",
    )

    protect_receivables = forms.BooleanField(required=False, label="Protect Receivables", widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-300"}))
    protect_payables = forms.BooleanField(required=False, label="Protect Payables", widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-300"}))
    protect_cash_in_hand = forms.BooleanField(required=False, label="Protect Cash in Hand", widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-300"}))
    protect_inventory = forms.BooleanField(required=False, label="Protect Inventory", widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-300"}))

    class Meta:
        model = UserSettings
        fields = [
            "business_name", "barcode_printer_name", "default_sale_payment_method", "default_sale_business",
            "protect_receivables", "protect_payables", "protect_cash_in_hand", "protect_inventory",
        ]
        widgets = {
            "business_name": forms.TextInput(attrs={
                "class": "w-full rounded-lg border border-slate-300 px-3 py-2",
                "placeholder": "Enter business name for barcode labels"
            }),
            "barcode_printer_name": forms.TextInput(attrs={
                "class": "w-full rounded-lg border border-slate-300 px-3 py-2",
                "placeholder": "Enter printer name (e.g., BC-LP1300)"
            }),
            "default_sale_business": forms.Select(attrs={
                "class": "w-full rounded-lg border border-slate-300 px-3 py-2"
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set up queryset for default_sale_business
        self.fields["default_sale_business"].queryset = Business.objects.filter(
            is_active=True,
            is_deleted=False
        ).order_by("name")
        self.fields["default_sale_business"].empty_label = "None (select manually each time)"

    def clean(self):
        from django.contrib.auth.hashers import check_password
        data = super().clean()
        new_pw = (data.get("cancellation_password_new") or "").strip()
        old_pw = (data.get("cancellation_password_old") or "").strip()
        remove = data.get("remove_cancellation_password") is True
        settings_obj = self.instance
        has_existing = bool(getattr(settings_obj, "cancellation_password", None) or "")

        if remove:
            if not has_existing:
                self.add_error("remove_cancellation_password", "No cancellation password is set.")
            elif not old_pw:
                self.add_error(
                    "cancellation_password_old",
                    "Current password is required to remove the cancellation password.",
                )
            elif has_existing:
                stored = getattr(settings_obj, "cancellation_password", "") or ""
                if not stored or not check_password(old_pw, stored):
                    self.add_error(
                        "cancellation_password_old",
                        "Current cancellation password is incorrect.",
                    )
            if new_pw and not self.errors:
                self.add_error(
                    "cancellation_password_new",
                    "Clear 'New password' when removing; or uncheck 'Remove' to change instead.",
                )
        elif new_pw:
            if has_existing and not old_pw:
                self.add_error(
                    "cancellation_password_old",
                    "Current cancellation password is required to change it.",
                )
            elif has_existing and old_pw:
                stored = getattr(settings_obj, "cancellation_password", "") or ""
                if not stored or not check_password(old_pw, stored):
                    self.add_error(
                        "cancellation_password_old",
                        "Current cancellation password is incorrect.",
                    )
        return data
    

class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = [
            "name",
            "bank_name",
            "account_number",
            "branch",
            "opening_balance",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": BASE_INPUT}),
            "bank_name": forms.TextInput(attrs={"class": BASE_INPUT}),
            "account_number": forms.TextInput(attrs={"class": BASE_INPUT}),
            "branch": forms.TextInput(attrs={"class": BASE_INPUT}),
            "opening_balance": forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
            # checkbox shouldn't look like a text input
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-300"}),
        }


class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ["name", "bank_name", "account_number", "branch", "opening_balance", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": BASE_INPUT}),
            "bank_name": forms.TextInput(attrs={"class": BASE_INPUT}),
            "account_number": forms.TextInput(attrs={"class": BASE_INPUT}),
            "branch": forms.TextInput(attrs={"class": BASE_INPUT}),
            "opening_balance": forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-300"}),
        }

class BankMovementForm(forms.ModelForm):
    # Only used for movement_type = CHEQUE_DEPOSIT
    cheques = forms.ModelMultipleChoiceField(
        label="Pending cheques to deposit",
        queryset=Payment.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    # Only used for Cash -> Bank closing movement
    use_cash_in_hand = forms.BooleanField(
        label="Use closing cash in hand",
        required=False,
    )

    class Meta:
        model = BankMovement
        fields = [
            "date",
            "movement_type",
            "amount",
            "from_bank",
            "to_bank",
            "party",           # can be used for any movement. especially CHEQUE_PAYMENT
            "purchase_order",  # optional link with PO
            "method",
            "reference_no",
            "notes",
            "cheques",          # virtual helper field. not on model
            "use_cash_in_hand", # virtual helper field. not on model
        ]
        widgets = {
            "date": forms.DateInput(
                attrs={"type": "date", "class": BASE_INPUT}
            ),
            "movement_type": forms.Select(
                attrs={"class": BASE_INPUT, "id": "id_movement_type"}
            ),
            "amount": forms.NumberInput(
                attrs={"class": BASE_INPUT, "step": "0.01", "id": "id_amount"}
            ),
            "from_bank": forms.Select(
                attrs={"class": BASE_INPUT, "id": "id_from_bank"}
            ),
            "to_bank": forms.Select(
                attrs={"class": BASE_INPUT, "id": "id_to_bank"}
            ),
            "party": forms.Select(
                attrs={"class": BASE_INPUT, "id": "id_party"}
            ),
            "purchase_order": forms.Select(
                attrs={"class": BASE_INPUT, "id": "id_purchase_order"}
            ),
            "method": forms.TextInput(attrs={"class": BASE_INPUT}),
            "reference_no": forms.TextInput(attrs={"class": BASE_INPUT}),
            "notes": forms.TextInput(attrs={"class": BASE_INPUT}),
            "use_cash_in_hand": forms.CheckboxInput(
                attrs={
                    "class": "h-4 w-4 text-slate-900 border-slate-300 rounded",
                    "id": "id_use_cash_in_hand",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Pending cheques only. direction=IN. cheque. status pending
        self.fields["cheques"].queryset = (
            Payment.objects.filter(
                direction=Payment.IN,
                payment_method=Payment.PaymentMethod.CHEQUE,
                cheque_status=Payment.ChequeStatus.PENDING,
            )
            .select_related("party", "bank_account", "business")
            .order_by("date", "id")
        )
        self.fields["cheques"].widget.attrs["class"] = "space-y-1 text-sm"

        # Optional. nicer label for checkbox
        self.fields["use_cash_in_hand"].label = (
            "Use closing cash in hand for this Cash → Bank deposit"
        )

        # ---------- Party queryset (vendors or both) ----------
        party_field = self.fields.get("party")
        if party_field:
            party_field.queryset = (
                Party.objects.all().order_by("display_name")
            )
            party_field.required = False

            # When editing. make sure initial is set from instance
            if not self.is_bound and self.instance.pk and self.instance.party_id:
                party_field.initial = self.instance.party_id

        # ---------- Purchase orders filtered by selected party ----------
        po_field = self.fields.get("purchase_order")
        if po_field:
            po_qs = (
                PurchaseOrder.objects.select_related("supplier")
                .order_by("-created_at")
            )

            # Decide which party we should filter by
            party_id = None

            if self.is_bound:
                # From POST data
                raw_party = self.data.get(self.add_prefix("party")) or ""
                party_id = raw_party.strip() or None
            else:
                # From instance on edit
                if self.instance.party_id:
                    party_id = str(self.instance.party_id)
                elif getattr(self.instance, "purchase_order_id", None):
                    # In case movement has a purchase_order but party not set
                    party_id = str(self.instance.purchase_order.supplier_id)

            if party_id and party_id.isdigit():
                po_qs = po_qs.filter(supplier_id=int(party_id))

            po_field.queryset = po_qs
            po_field.required = False

    def clean(self):
        cleaned = super().clean()
        mv_type = cleaned.get("movement_type")
        to_bank = cleaned.get("to_bank")
        cheques = cleaned.get("cheques")

        # ----- Cheque deposit special handling -----
        if mv_type == BankMovement.CHEQUE_DEPOSIT:
            if not cheques:
                self.add_error("cheques", "Please select at least one pending cheque.")
            if not to_bank:
                self.add_error("to_bank", "Please select the bank that will receive the cheques.")

            total = Decimal("0.00")
            if cheques:
                for ch in cheques:
                    total += ch.amount or Decimal("0.00")

            cleaned["amount"] = total
            self.instance.amount = total

        # ----- Bank → Cheque payment validations -----
        if mv_type == BankMovement.CHEQUE_PAYMENT:
            party = cleaned.get("party")
            po = cleaned.get("purchase_order")

            # Party is required for cheque payment
            if not party and not po:
                self.add_error("party", "Please select the party for this cheque payment.")
            elif not party and po:
                # If PO selected but party missing. auto set party from PO supplier
                cleaned["party"] = po.supplier
                self.instance.party = po.supplier
                party = po.supplier

            # Purchase order is OPTIONAL. only validate if provided
            if po and party and po.supplier_id != party.id:
                self.add_error(
                    "purchase_order",
                    "Selected purchase order does not belong to the chosen party.",
                )

        return cleaned

# Optional: a simple filter/search form for the ledger list
class CashFlowFilterForm(forms.Form):
    q = forms.CharField(required=False, widget=forms.TextInput(attrs={
        "class": BASE_INPUT,
        "placeholder": "Search description, amount, bank..."
    }))
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={
        "type": "date",
        "class": BASE_INPUT,
    }))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={
        "type": "date",
        "class": BASE_INPUT,
    }))
    flow_type = forms.ChoiceField(
        required=False,
        choices=(("", "All"),) + tuple(CashFlow.FLOW_TYPE),
        widget=forms.Select(attrs={"class": BASE_INPUT}),
    )
    bank_account = forms.ModelChoiceField(
        required=False,
        queryset=BankAccount.objects.all(),
        widget=forms.Select(attrs={"class": BASE_INPUT}),
    )

class PurchaseOrderForm(forms.ModelForm):
    PAYMENT_CHOICES = [
        ("none", "No immediate payment"),
        ("cash", "Cash"),
        ("bank", "Bank"),
    ]
    
    # NEW: Add date field
    po_date = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={
            "class": BASE_INPUT,
            "type": "date",
        }),
        label="PO Date",
        help_text="Purchase Order date (can be previous date)",
    )

    payment_method = forms.ChoiceField(
        choices=PAYMENT_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": BASE_INPUT}),
        help_text="Choose Cash/Bank to record a payment now.",
    )
    bank_account = forms.ModelChoiceField(
        queryset=BankAccount.objects.filter(is_active=True).order_by("name"),
        required=False,
        widget=forms.Select(attrs={"class": BASE_INPUT}),
        help_text="Required only when Payment method is Bank.",
    )
    paid_amount = forms.DecimalField(
        required=False,
        min_value=Decimal("0.00"),
        max_digits=12, decimal_places=2,
        widget=forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
        help_text="Optional immediate payment amount.",
    )

    class Meta:
        model = PurchaseOrder
        fields = [
            "business",
            "warehouse",
            "supplier",
            "status",
            "tax_percent",
            "discount_percent",
        ]
        widgets = {
            "business": forms.Select(attrs={"class": BASE_INPUT}),
            "supplier": forms.Select(attrs={"class": BASE_INPUT}),
            "status": forms.Select(attrs={"class": BASE_INPUT}),
            "tax_percent": forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
            "discount_percent": forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        self.fixed_business = kwargs.pop("fixed_business", None)
        super().__init__(*args, **kwargs)

        if self.fixed_business is not None:
            self.fields["business"].initial = self.fixed_business
            self.fields["business"].disabled = True
            self.fields["business"].widget.attrs["readonly"] = True

        # MODIFIED: Allow all party types (VENDOR, CUSTOMER, BOTH)
        self.fields["supplier"].queryset = (
            Party.objects
            .filter(is_active=True, is_deleted=False) # Show all active, non-deleted parties
            .order_by("display_name")
        )

        if not self.data and not self.initial.get("payment_method"):
            self.initial["payment_method"] = "none"
        
        if not self.instance.pk and not self.initial.get("po_date"):
            self.initial["po_date"] = timezone.localdate()
        elif self.instance.pk and self.instance.created_at:
            self.initial["po_date"] = timezone.localdate(self.instance.created_at)

class PurchaseOrderItemForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrderItem
        fields = ["product", "quantity", "uom", "size_per_unit", "unit_price", "sale_price"]  # Added sale_price
        widgets = {
            "product": forms.Select(attrs={"class": "form-control product-select"}),
            "uom": forms.HiddenInput(),  # ← Hidden input
            "size_per_unit": forms.HiddenInput(),  # ← Hidden input
            "quantity": forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.000001"}),
            "unit_price": forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
            "sale_price": forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01", "placeholder": "Sale Price"}),
        }

    def __init__(self, *args, **kwargs):
        business = kwargs.pop("business", None)
        super().__init__(*args, **kwargs)
        if business:
            self.fields["product"].queryset = Product.objects.filter(business=business).order_by("name")
        else:
            self.fields["product"].queryset = Product.objects.order_by("name")

from django.forms import inlineformset_factory

PurchaseOrderItemFormSet = inlineformset_factory(
    parent_model=PurchaseOrder,
    model=PurchaseOrderItem,
    form=PurchaseOrderItemForm,
    extra=1,
    can_delete=True,
    validate_min=True,
    min_num=1,
)

# Form for expenses linked to PO
class PurchaseOrderExpenseForm(forms.ModelForm):
    category = forms.ChoiceField(
        choices=getattr(Expense, 'category', models.CharField()).field.choices if hasattr(Expense, 'category') else [],
        widget=forms.Select(attrs={"class": "w-full rounded-lg border-slate-300 text-sm"})
    )

    class Meta:
        model = Expense
        fields = [
            "category", "amount", "description", "reference",
            "party", "payment_source", "bank_account", "is_paid", "divide_per_unit",
        ]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "w-full rounded-lg border-slate-300 text-sm", "step": "0.01"}),
            "description": forms.TextInput(attrs={"class": "w-full rounded-lg border-slate-300 text-sm", "placeholder": "Description"}),
            "reference": forms.TextInput(attrs={"class": "w-full rounded-lg border-slate-300 text-sm", "placeholder": "Ref"}),
            "party": forms.Select(attrs={"class": "w-full rounded-lg border-slate-300 text-sm"}),
            "payment_source": forms.Select(attrs={"class": "w-full rounded-lg border-slate-300 text-sm"}),
            "bank_account": forms.Select(attrs={"class": "w-full rounded-lg border-slate-300 text-sm"}),
            "is_paid": forms.CheckboxInput(attrs={"class": "rounded border-slate-300 text-indigo-600 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200 focus:ring-opacity-50"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Manually set choices from model if not picking up automatically
        from .models import ExpenseCategory
        self.fields['category'].choices = [('', '---------')] + list(ExpenseCategory.choices)
        
        # Payment fields are optional unless is_paid is True
        self.fields["payment_source"].required = False
        self.fields["bank_account"].required = False

        # In PO context, we don't need business/po fields as they are handled by view/factory
        if "business" in self.fields: del self.fields["business"]
        if "purchase_order" in self.fields: del self.fields["purchase_order"]
        if "attachment" in self.fields: del self.fields["attachment"]
        if "staff" in self.fields: del self.fields["staff"]

    def clean(self):
        cleaned_data = super().clean()
        is_paid = cleaned_data.get("is_paid")
        payment_source = cleaned_data.get("payment_source")
        bank_account = cleaned_data.get("bank_account")

        if is_paid:
            if not payment_source:
                self.add_error("payment_source", "Required for instant payment.")
            if payment_source == "bank" and not bank_account:
                self.add_error("bank_account", "Bank account required for bank payments.")
        
        return cleaned_data

PurchaseOrderExpenseFormSet = inlineformset_factory(
    parent_model=PurchaseOrder,
    model=Expense,
    form=PurchaseOrderExpenseForm,
    extra=0,
    can_delete=True,
)


class PurchaseReturnForm(forms.ModelForm):
    """
    Main Purchase Return form.
    Adds refund controls:
      - refund_method: 'cash' | 'bank' | 'none'
      - bank_account: required when refund_method == 'bank'
      - received_amount: optional amount to record now (will be clamped by view)
    """
    REFUND_METHOD_CHOICES = [
        ("none", "No immediate refund"),
        ("cash", "Cash"),
        ("bank", "Bank"),
    ]

    refund_method = forms.ChoiceField(
        choices=REFUND_METHOD_CHOICES,
        required=False,
        initial="none",
        widget=forms.Select(attrs={"class": BASE_INPUT}),
        label="Refund method",
    )
    bank_account = forms.ModelChoiceField(
        queryset=BankAccount.objects.filter(is_active=True).order_by("name"),
        required=False,
        widget=forms.Select(attrs={"class": BASE_INPUT}),
        label="Bank account",
    )
    received_amount = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=12, decimal_places=2,
        widget=forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
        label="Refund amount",
        help_text="Amount to record as refund now",
    )

    class Meta:
        model = PurchaseReturn
        fields = [
            "business", "supplier", "status",
            "tax_percent", "discount_percent",
            "notes",
        ]
        widgets = {
            "business":        forms.Select(attrs={"class": BASE_INPUT}),
            "supplier":        forms.Select(attrs={"class": BASE_INPUT}),
            "status":          forms.Select(attrs={"class": BASE_INPUT}),
            "tax_percent":     forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
            "discount_percent":forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
            "notes":           forms.Textarea(attrs={"class": BASE_INPUT, "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # MODIFIED: Allow all active, non-deleted parties for returns
        self.fields["supplier"].queryset = (
            Party.objects
            .filter(is_active=True, is_deleted=False)
            .order_by("display_name")
        )

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("refund_method") or "none"
        bank   = cleaned.get("bank_account")
        if method == "bank" and not bank:
            self.add_error("bank_account", "Please select a bank account for bank refunds.")
        return cleaned

class PurchaseReturnItemForm(forms.ModelForm):
    class Meta:
        model = PurchaseReturnItem
        fields = ["product", "quantity", "uom", "size_per_unit", "unit_price"]
        widgets = {
            "product":    forms.Select(attrs={"class": BASE_INPUT}),
            "uom": forms.HiddenInput(),  # Hidden input
            "size_per_unit": forms.HiddenInput(),  # Hidden input
            "quantity":   forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.000001"}),
            "unit_price": forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        business = kwargs.pop("business", None)
        super().__init__(*args, **kwargs)
        if business:
            self.fields["product"].queryset = Product.objects.filter(
                business=business
            ).order_by("name")
        else:
            self.fields["product"].queryset = Product.objects.order_by("name")

PurchaseReturnItemFormSet = inlineformset_factory(
    parent_model=PurchaseReturn,
    model=PurchaseReturnItem,
    form=PurchaseReturnItemForm,
    extra=1,
    can_delete=True,
    validate_min=True,
    min_num=1,
)


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = [
            "business", "date", "category", "amount", "description", "reference",
            "attachment", "party", "staff", "purchase_order",
            "payment_source", "bank_account", "is_paid", "divide_per_unit",
        ]
        widgets = {
            "business":       forms.Select(attrs={"class": BASE_INPUT}),
            "date":           forms.DateInput(attrs={"type": "date", "class": BASE_INPUT}),
            "category":       forms.Select(attrs={"class": BASE_INPUT}),
            "amount":         forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01", "min": "0"}),
            "description":    forms.TextInput(attrs={"class": BASE_INPUT, "autocomplete": "off", "placeholder": "Optional"}),
            "reference":      forms.TextInput(attrs={"class": BASE_INPUT, "autocomplete": "off", "placeholder": "Bill/Invoice ref (optional)"}),
            "attachment":     forms.ClearableFileInput(attrs={"class": BASE_INPUT}),
            "party":          forms.Select(attrs={"class": BASE_INPUT}),
            "staff":          forms.Select(attrs={"class": BASE_INPUT}),
            "purchase_order": forms.Select(attrs={"class": BASE_INPUT}),
            "payment_source": forms.Select(attrs={"class": BASE_INPUT}),
            "bank_account":   forms.Select(attrs={"class": BASE_INPUT}),
            "divide_per_unit": forms.CheckboxInput(attrs={"class": "rounded border-slate-300 text-blue-600 focus:ring-blue-500"}),
        }

    def __init__(self, *args, **kwargs):
        selected_business: Business | None = kwargs.pop("selected_business", None)
        super().__init__(*args, **kwargs)

        # Party is optional by default. requirement enforced in clean() for Purchases only
        self.fields["party"].queryset = Party.objects.filter(
            is_active=True, is_deleted=False
        ).order_by("display_name")
        self.fields["party"].empty_label = "— (optional) —"

        # If no selected_business from view. fall back to instance or posted/initial value
        if not selected_business:
            if getattr(self.instance, "pk", None) and getattr(self.instance, "business_id", None):
                selected_business = self.instance.business
            else:
                raw_biz = None
                if self.is_bound:
                    raw_biz = self.data.get(self.add_prefix("business"))
                else:
                    raw_biz = self.initial.get("business")
                if raw_biz:
                    try:
                        selected_business = Business.objects.filter(pk=int(raw_biz)).first()
                    except (TypeError, ValueError):
                        selected_business = None

        # Staff queryset and base PurchaseOrder queryset by business
        if selected_business:
            self.fields["staff"].queryset = Staff.objects.filter(
                business=selected_business, is_deleted=False, is_active=True
            ).order_by("full_name")

            po_qs = PurchaseOrder.objects.filter(
                business=selected_business,
                is_active=True,
                is_deleted=False,
            )
            # Preselect business if nothing provided
            if (
                not self.initial.get("business")
                and not (self.is_bound and self.data.get(self.add_prefix("business")))
            ):
                self.initial["business"] = selected_business.pk
        else:
            # Business is optional. show all active staff. POs empty
            self.fields["staff"].queryset = Staff.objects.filter(
                is_deleted=False, is_active=True
            ).order_by("full_name")
            po_qs = PurchaseOrder.objects.none()

        # Detect currently selected party (vendor) to filter POs
        party_id = None
        if self.is_bound:
            raw_party = self.data.get(self.add_prefix("party"))
            if raw_party and str(raw_party).isdigit():
                party_id = int(raw_party)
        else:
            if self.instance and getattr(self.instance, "pk", None) and getattr(self.instance, "party_id", None):
                party_id = self.instance.party_id
            else:
                init_party = self.initial.get("party")
                if init_party:
                    party_id = getattr(init_party, "pk", init_party)

        if party_id:
            po_qs = po_qs.filter(supplier_id=party_id)

        self.fields["purchase_order"].queryset = po_qs.order_by("-created_at")

        self.fields["staff"].empty_label = "— (optional) —"
        self.fields["purchase_order"].empty_label = "— (optional) —"
        self.fields["payment_source"].label = "Paid from"
        self.fields["bank_account"].label = "Bank account (if Paid from = Bank)"

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get("category")
        party = cleaned.get("party")

        # Require Party only when category is Purchases/Other Items
        if category == ExpenseCategory.PURCHASE and not party:
            self.add_error("party", "Supplier/Party is required for Purchases/Other Items.")
        return cleaned

    def clean_amount(self):
        amt = self.cleaned_data.get("amount") or Decimal("0")
        if amt <= 0:
            raise forms.ValidationError("Amount must be positive.")
        return amt


from decimal import Decimal
from django import forms
from django.db.models import Q
from django.forms import inlineformset_factory

from .models import SalesOrder, SalesOrderItem, Product, Business, BankAccount, Party

BASE_INPUT = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2"

# Row inputs inside the grid: borderless, right-aligned
ROW_INPUT = "w-full bg-transparent border-0 px-0 py-2 text-right focus:outline-none focus:ring-0"

from django import forms
from django.utils import timezone
from django.db.models import Q
from decimal import Decimal
from datetime import timedelta
from .models import SalesOrder, Business, Party, BankAccount


class SalesOrderForm(forms.ModelForm):
    RECEIPT_METHOD_CHOICES = [
        ("cash", "Cash"),
        ("bank", "Bank"),
        ("card", "Card Payment"),
        ("on_credit", "On Credit"),
    ]

    order_date = forms.DateTimeField(
        required=True,
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
        widget=forms.DateTimeInput(
            attrs={
                "type": "datetime-local", 
                "class": BASE_INPUT,
                "step": "60"  # 60 seconds = 1 minute precision
            },
            format='%Y-%m-%dT%H:%M'
        ),
        label="Order date & time",
    )

    receipt_method = forms.ChoiceField(
        choices=RECEIPT_METHOD_CHOICES,
        required=False,
        initial="cash",  # Auto-select cash by default
        widget=forms.Select(attrs={"class": BASE_INPUT}),
    )

    bank_account = forms.ModelChoiceField(
        queryset=BankAccount.objects.filter(is_active=True).order_by("name"),
        required=False,
        widget=forms.Select(attrs={"class": BASE_INPUT}),
    )

    received_amount = forms.DecimalField(
        required=False,
        min_value=Decimal("0.00"),
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
    )

    class Meta:
        model = SalesOrder
        fields = [
            "business", "customer", "customer_name", "customer_phone",
            "status", "notes", "tax_percent", "discount_percent",
        ]
        widgets = {
            "business": forms.HiddenInput(),
            "customer": forms.Select(attrs={"class": BASE_INPUT}),
            "customer_name": forms.TextInput(attrs={"class": BASE_INPUT, "placeholder": "Customer name"}),
            "customer_phone": forms.TextInput(attrs={"class": BASE_INPUT, "placeholder": "03xx-xxxxxxx"}),
            "status": forms.Select(attrs={"class": BASE_INPUT}),
            "notes": forms.TextInput(attrs={"class": BASE_INPUT}),
            "tax_percent": forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
            "discount_percent": forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        self.business = kwargs.pop("business", None)
        super().__init__(*args, **kwargs)

        # --- STATUS FIELD RESTRICTION ---
        # If status is FULFILLED, only allow CANCELLED option
        if self.instance and self.instance.pk:
            if self.instance.status == SalesOrder.Status.FULFILLED:
                self.fields["status"].choices = [
                    (SalesOrder.Status.FULFILLED, "Fulfilled"),
                    (SalesOrder.Status.CANCELLED, "Cancelled"),
                ]
            # If cancelled, keep all choices (can change back)

        # --- DATE & TIME LOGIC (FIXED) ---
        if self.instance and self.instance.pk and self.instance.created_at:
            # EDIT MODE: Display the original timestamp in Pakistan time
            # Convert UTC (stored in DB) to Asia/Karachi time
            local_dt = timezone.localtime(self.instance.created_at)
            # datetime-local input needs naive datetime (without timezone info)
            # So we take the local time and make it naive for the input
            naive_local = local_dt.replace(tzinfo=None)
            formatted_date = naive_local.strftime('%Y-%m-%dT%H:%M')
            
            # Make field read-only to prevent accidental timestamp changes
            self.fields['order_date'].widget.attrs['readonly'] = True
            self.fields['order_date'].widget.attrs['class'] = BASE_INPUT + ' bg-gray-100 cursor-not-allowed'
            self.fields['order_date'].widget.attrs['title'] = 'Order date/time cannot be changed after creation'
            self.fields['order_date'].initial = naive_local
            self.fields['order_date'].widget.attrs['value'] = formatted_date
            self.fields['order_date'].required = False  # Don't validate on edit since it's readonly
            
        else:
            # CREATE MODE: Current Pakistan time (only for new orders)
            curr_time = timezone.now()
            local_time = timezone.localtime(curr_time)
            # Make naive for datetime-local input
            naive_local = local_time.replace(tzinfo=None)
            formatted_date = naive_local.strftime('%Y-%m-%dT%H:%M')
            self.fields['order_date'].initial = naive_local
            self.fields['order_date'].widget.attrs['value'] = formatted_date

        # --- Bind Business ---
        self.fields["business"].queryset = Business.objects.order_by("name", "id")
        if self.business:
            self.fields["business"].initial = self.business.id

        # --- Party/Customer Queryset ---
        qs_party = (
            Party.objects
            .filter(is_active=True, is_deleted=False)
            .filter(Q(type="CUSTOMER") | Q(type="VENDOR") | Q(type="BOTH"))
            .order_by("display_name")
            .distinct()
        )
        self.fields["customer"].queryset = qs_party
        self.fields["customer"].required = False
        
        # --- Bank Account Filtering ---
        # Include business-specific accounts AND global/shared accounts (where business is NULL)
        qs_bank = BankAccount.objects.filter(is_active=True)
        if self.business:
            qs_bank = qs_bank.filter(Q(business=self.business) | Q(business__isnull=True))
        else:
            # If no business context, show all active accounts
            pass
        
        self.fields["bank_account"].queryset = qs_bank.order_by("name")


class SalesOrderItemForm(forms.ModelForm):
    class Meta:
        model = SalesOrderItem
        fields = ["product", "quantity", "uom", "size_per_unit", "unit_price"]
        widgets = {
            "product": forms.Select(attrs={"class": BASE_INPUT}),
            "quantity": forms.NumberInput(attrs={"class": ROW_INPUT, "step": "0.000001"}),
            "uom": forms.HiddenInput(),  # Hidden - auto-selected as base UOM
            "size_per_unit": forms.HiddenInput(),  # Hidden - auto-set to 1.0 for base UOM
            "unit_price": forms.NumberInput(attrs={"class": ROW_INPUT, "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        _business = kwargs.pop("business", None)
        super().__init__(*args, **kwargs)

        self.fields["product"].queryset = (
            Product.objects
            .filter(is_active=True, is_deleted=False)
            .order_by("name")
        )

from django import forms
from django.utils import timezone
from django.db.models import Q
from decimal import Decimal
from datetime import timedelta  # Required for the manual time offset
from .models import SalesOrder, Business, Party, BankAccount
from datetime import timedelta # Add this import at the top

SalesOrderItemFormSet = inlineformset_factory(
    parent_model=SalesOrder,
    model=SalesOrderItem,
    form=SalesOrderItemForm,
    extra=1,
    can_delete=True,
    validate_min=True,
    min_num=1,
)

ROW_INPUT  = "w-full bg-transparent border-0 px-0 py-2 text-right focus:outline-none focus:ring-0"
BASE_INPUT = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2"

class SalesReturnForm(forms.ModelForm):
    REFUND_METHOD_CHOICES = [
        ("cash", "Cash"),
        ("bank", "Bank"),
        ("card", "Card Payment"),
        ("on_credit", "On Credit"),
    ]

    refund_method = forms.ChoiceField(
        choices=REFUND_METHOD_CHOICES,
        required=False,
        initial="cash",
        widget=forms.Select(attrs={"class": BASE_INPUT}),
    )
    bank_account = forms.ModelChoiceField(
        queryset=BankAccount.objects.filter(is_active=True).order_by("name"),
        required=False,
        widget=forms.Select(attrs={"class": BASE_INPUT}),
    )
    refund_amount = forms.DecimalField(
        required=False, min_value=Decimal("0.00"),
        max_digits=12, decimal_places=2,
        widget=forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
    )

    class Meta:
        model = SalesReturn
        fields = [
            "business",
            "source_order",     # Optional - can be None for manual returns
            "customer",         # kept for Party id; hidden via widget attrs below
            "customer_name",    # visible text box user will type into
            "customer_phone",
            "status",
            "notes",
            "tax_percent",
            "discount_percent",
        ]
        widgets = {
            "business": forms.Select(attrs={"class": BASE_INPUT}),
            "source_order": forms.Select(attrs={"class": BASE_INPUT, "style": "display:none;"}),  # Hidden - optional
            # Hide the select; JS will set its value from the typed name
            "customer": forms.Select(attrs={
                "class": BASE_INPUT,
                "style": "display:none !important;",
                "tabindex": "-1",
                "aria-hidden": "true",
            }),
            "status": forms.Select(attrs={"class": BASE_INPUT}),
            "notes": forms.TextInput(attrs={"class": BASE_INPUT}),
            "tax_percent": forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
            "discount_percent": forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        self.business = kwargs.pop("business", None)
        super().__init__(*args, **kwargs)

        # Default status to pending for new returns
        if not self.data and not self.instance.pk:
            self.initial["status"] = SalesReturn.Status.PENDING
        
        # Default refund method to cash for fresh form
        if not self.data and not self.initial.get("refund_method"):
            self.initial["refund_method"] = "cash"

        # Make the visible inputs look right and disable browser autofill noise
        self.fields["customer_name"].widget.attrs.update({
            "class": "w-full rounded-lg border-2 border-indigo-300 bg-white px-3 py-2",
            "placeholder": "Type customer name…",
            "autocomplete": "off",
        })
        self.fields["customer_phone"].widget.attrs.update({
            "class": "w-full rounded-lg border-2 border-indigo-300 bg-white px-3 py-2",
            "placeholder": "Optional phone",
        })
        self.fields["notes"].widget.attrs.update({
            "placeholder": "Notes (optional)",
        })

        # Business selector + initial
        self.fields["business"].queryset = Business.objects.order_by("name", "id")
        if self.business:
            self.fields["business"].initial = self.business.id

        # MODIFIED: Allow all active, non-deleted parties for returns (Unified Party System)
        self.fields["customer"].queryset = (
            Party.objects
            .filter(is_active=True, is_deleted=False)
            .order_by("display_name")
            .distinct()
        )

        # Sales Orders scoped to current business (excluding cancelled orders)
        # source_order is optional - can be None for manual returns
        if self.business:
            self.fields["source_order"].queryset = (
                SalesOrder.objects
                .filter(business=self.business, status__in=[SalesOrder.Status.OPEN, SalesOrder.Status.FULFILLED])
                .exclude(status=SalesOrder.Status.CANCELLED)
                .order_by("-created_at", "-id")
            )
            self.fields["source_order"].required = False
        else:
            self.fields["source_order"].queryset = SalesOrder.objects.none()
            self.fields["source_order"].required = False

        # Bank accounts (optionally per business)
        qs_bank = BankAccount.objects.filter(is_active=True).order_by("name")
        try:
            BankAccount._meta.get_field("business")
        except Exception:
            pass
        else:
            if self.business:
                qs_bank = qs_bank.filter(business=self.business)
        self.fields["bank_account"].queryset = qs_bank

class SalesReturnItemForm(forms.ModelForm):
    class Meta:
        model = SalesReturnItem
        fields = ["product", "quantity", "unit_price"]
        widgets = {
            "product": forms.Select(attrs={"class": BASE_INPUT}),
            "quantity": forms.NumberInput(attrs={"class": ROW_INPUT, "step": "0.000001"}),
            "unit_price": forms.NumberInput(attrs={"class": ROW_INPUT, "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        business = kwargs.pop("business", None)
        super().__init__(*args, **kwargs)
        if business:
            # Filter by business, but also include any products that might be submitted in POST
            # This ensures products added via JavaScript are valid during form validation
            qs = Product.objects.filter(business=business, is_active=True, is_deleted=False).order_by("name")
            
            # If POST data has a product value, ensure it's included even if not in business queryset
            if self.data:
                prefix = self.prefix or ''
                product_key = f'{prefix}-product' if prefix else 'product'
                product_id = self.data.get(product_key)
                if product_id:
                    try:
                        product_id_int = int(product_id)
                        if not qs.filter(pk=product_id_int).exists():
                            # Include this product even if it's not in business queryset
                            qs = qs | Product.objects.filter(pk=product_id_int, is_active=True, is_deleted=False)
                    except (ValueError, TypeError):
                        pass
            
            self.fields["product"].queryset = qs.distinct()
        else:
            self.fields["product"].queryset = Product.objects.filter(is_active=True, is_deleted=False).order_by("name")

SalesReturnItemFormSet = inlineformset_factory(
    parent_model=SalesReturn,
    model=SalesReturnItem,
    form=SalesReturnItemForm,
    extra=1,
    can_delete=True,
    validate_min=True,
    min_num=1,
)

class SalesInvoiceForm(forms.ModelForm):
    # extra fields to add a receipt while editing
    RECEIPT_CHOICES = [
        ("none", "No receipt now"),
        ("cash", "Cash"),
        ("bank", "Bank"),
    ]
    receipt_method  = forms.ChoiceField(choices=RECEIPT_CHOICES, initial="none", required=False)
    bank_account    = forms.ModelChoiceField(queryset=BankAccount.objects.filter(is_active=True), required=False)
    received_amount = forms.DecimalField(required=False, min_value=Decimal("0.00"), max_digits=12, decimal_places=2)

    class Meta:
        model = SalesInvoice
        fields = [
            "business", "customer", "status",
            "tax_percent", "discount_percent", "notes",
        ]
        widgets = {
            "business":        forms.Select(attrs={"class": BASE_INPUT}),
            "customer":        forms.Select(attrs={"class": BASE_INPUT}),
            "status":          forms.Select(attrs={"class": BASE_INPUT}),
            "tax_percent":     forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
            "discount_percent":forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
            "notes":           forms.TextInput(attrs={"class": BASE_INPUT}),
        }

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("receipt_method") or "none"
        bank   = cleaned.get("bank_account")
        amount = cleaned.get("received_amount") or Decimal("0.00")
        if method == "bank" and not bank:
            self.add_error("bank_account", "Please select a Bank Account for bank receipts.")
        if amount and amount < 0:
            self.add_error("received_amount", "Amount must be positive.")
        return cleaned

class SalesInvoiceItemForm(forms.ModelForm):
    class Meta:
        model = SalesInvoiceItem
        fields = ["product", "quantity", "unit_price"]
        widgets = {
            "product":   forms.Select(attrs={"class": BASE_INPUT}),
            "quantity":  forms.NumberInput(attrs={"class": BASE_INPUT, "step": "1", "min": "0"}),
            "unit_price":forms.NumberInput(attrs={"class": BASE_INPUT, "step": "0.01"}),
        }

SalesInvoiceItemFormSet = inlineformset_factory(
    parent_model=SalesInvoice,
    model=SalesInvoiceItem,
    form=SalesInvoiceItemForm,
    extra=0,        # we will render existing items; add via +Add Row
    can_delete=True,
)



#-----------
#  Warehouse THings
#-------------

# barkat/forms.py
from decimal import Decimal
from django import forms
from django.db import transaction
from django.core.exceptions import ValidationError

from .models import (
    Warehouse,
    WarehouseStock,
    BusinessStock,
    StockMove,
    Product,
    Business,
)


# ----------------------------
# Helpers / mixins
# ----------------------------
class AuditUserMixin:
    """
    Call form.save(user=request.user) to set created_by / updated_by
    on models that inherit TimeStampedBy.
    """
    def save(self, user=None, commit=True):
        obj = super().save(commit=False)
        if user is not None:
            # updated_by always
            if hasattr(obj, "updated_by"):
                obj.updated_by = user
            # created_by on create
            if getattr(obj, "pk", None) is None and hasattr(obj, "created_by"):
                obj.created_by = user
        if commit:
            obj.save()
            # handle m2m if needed
            if hasattr(self, "save_m2m"):
                self.save_m2m()
        return obj


# ----------------------------
# Warehouse
# ----------------------------
class WarehouseForm(AuditUserMixin, forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ["name", "code", "address", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Main Warehouse"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "WH-001"}),
            "address": forms.TextInput(attrs={"class": "form-control", "placeholder": "Street, City"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

# ----------------------------
# Stock move
# ----------------------------
class StockMoveForm(AuditUserMixin, forms.ModelForm):
    """
    Use this for the stock transfer page. It keeps the model’s own validation
    and adds a couple of helpful constraints at form level.
    """
    class Meta:
        model = StockMove
        fields = [
            "product",
            "source_warehouse", "source_business",
            "dest_warehouse", "dest_business",
            "quantity",
            "reference",
            "status",
        ]
        widgets = {
            "product": forms.Select(attrs={"class": "form-select"}),
            "source_warehouse": forms.Select(attrs={"class": "form-select"}),
            "source_business": forms.Select(attrs={"class": "form-select"}),
            "dest_warehouse": forms.Select(attrs={"class": "form-select"}),
            "dest_business": forms.Select(attrs={"class": "form-select"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.000001", "min": "0"}),
            "reference": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional reference"}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        """
        Optional filtering:
        - pass business=Business instance to filter products by business
        - pass product_qs=Product queryset to fully control product choices
        - pass source_only=True to show only source fields first (for step-by-step UI)
        """
        self.context_business = kwargs.pop("business", None)
        product_qs = kwargs.pop("product_qs", None)
        super().__init__(*args, **kwargs)

        # Product choices
        if product_qs is not None:
            self.fields["product"].queryset = product_qs
        elif self.context_business is not None:
            self.fields["product"].queryset = Product.objects.filter(business=self.context_business)
        else:
            # Reasonable default: active products if you track is_active
            self.fields["product"].queryset = Product.objects.all()

        # If a business is provided, limit the business selectors to it
        if self.context_business is not None:
            self.fields["source_business"].queryset = Business.objects.filter(pk=self.context_business.pk)
            self.fields["dest_business"].queryset = Business.objects.filter(pk=self.context_business.pk)

    def clean(self):
        cleaned = super().clean()
        product = cleaned.get("product")
        sb = cleaned.get("source_business")
        db = cleaned.get("dest_business")
        sw = cleaned.get("source_warehouse")
        dw = cleaned.get("dest_warehouse")
        qty = cleaned.get("quantity")

        # mirror the model helper early so the user gets instant form errors
        src_count = int(bool(sw)) + int(bool(sb))
        dst_count = int(bool(dw)) + int(bool(db))
        if src_count != 1 or dst_count != 1:
            raise ValidationError("Please choose exactly one source and one destination.")

        if qty is None or qty <= 0:
            raise ValidationError("Quantity must be positive.")

        # product belongs to one business; if a Business side is used, it must match
        prod_business_id = getattr(product, "business_id", None)
        if sb and sb.pk != prod_business_id:
            raise ValidationError("Product business must match the selected source business.")
        if db and db.pk != prod_business_id:
            raise ValidationError("Product business must match the selected destination business.")

        # same-to-same guard at form level too
        if sw and dw and sw.pk == dw.pk:
            raise ValidationError("Source and destination warehouse cannot be the same.")
        if sb and db and sb.pk == db.pk:
            raise ValidationError("Source and destination business cannot be the same.")

        return cleaned

    @transaction.atomic
    def save(self, user=None, commit=True):
        """
        Let the model’s post() do the actual stock movement when status is POSTED.
        If you want to always create in DRAFT first, leave as is and post from the view.
        """
        obj = super().save(user=user, commit=commit)
        # If the user chose "posted" in the form, apply movement right away
        if obj.status == StockMove.Status.POSTED and commit:
            obj.post(user=user)
        return obj

# ----------------------------
# Optional: quick refill/adjust forms
# ----------------------------
class WarehouseStockRefillForm(AuditUserMixin, forms.Form):
    """
    Simple refill form for the Warehouse detail screen.
    It creates or updates WarehouseStock for a product.
    """
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"})
    )
    quantity = forms.DecimalField(
        min_value=Decimal("0.000001"),
        decimal_places=6,
        max_digits=18,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.000001"})
    )

    def __init__(self, *args, **kwargs):
        """
        Pass warehouse and optional business to filter available products.
        """
        self.warehouse = kwargs.pop("warehouse", None)
        business = kwargs.pop("business", None)
        super().__init__(*args, **kwargs)

        if business is not None:
            self.fields["product"].queryset = Product.objects.filter(business=business)
        else:
            self.fields["product"].queryset = Product.objects.all()

        if self.warehouse is None:
            raise ValueError("WarehouseStockRefillForm requires warehouse=...")

    @transaction.atomic
    def save(self, user=None):
        product = self.cleaned_data["product"]
        qty = self.cleaned_data["quantity"] or Decimal("0")
        row, _ = WarehouseStock.objects.get_or_create(
            warehouse=self.warehouse,
            product=product,
            defaults={"quantity": Decimal("0")}
        )
        row.quantity = (row.quantity or Decimal("0")) + qty
        if user is not None:
            if hasattr(row, "updated_by"):
                row.updated_by = user
            if getattr(row, "pk", None) is None and hasattr(row, "created_by"):
                row.created_by = user
        row.full_clean()
        row.save(update_fields=["quantity", "updated_at", "updated_by"])
        return row


class BusinessStockAdjustForm(AuditUserMixin, forms.Form):
    """
    Optional: for direct manual corrections at business level (if you allow it).
    You might prefer to drive BusinessStock only via StockMove WH<->Business.
    """
    business = forms.ModelChoiceField(
        queryset=Business.objects.all(),
        widget=forms.Select(attrs={"class": "form-select"})
    )
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"})
    )
    new_quantity = forms.DecimalField(
        min_value=Decimal("0"),
        decimal_places=6,
        max_digits=18,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.000001"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Dynamically narrow product by selected business if POSTed
        if "business" in self.data:
            try:
                biz_id = int(self.data.get("business"))
                self.fields["product"].queryset = Product.objects.filter(business_id=biz_id)
            except (TypeError, ValueError):
                self.fields["product"].queryset = Product.objects.none()
        else:
            # initial load
            self.fields["product"].queryset = Product.objects.none()

    def clean(self):
        cleaned = super().clean()
        business = cleaned.get("business")
        product = cleaned.get("product")
        if business and product and product.business_id != business.pk:
            raise ValidationError("Selected product does not belong to the chosen business.")
        return cleaned

    @transaction.atomic
    def save(self, user=None):
        business = self.cleaned_data["business"]
        product = self.cleaned_data["product"]
        new_qty = self.cleaned_data["new_quantity"] or Decimal("0")

        row, _ = BusinessStock.objects.get_or_create(
            business=business, product=product,
            defaults={"quantity": Decimal("0")}
        )
        row.quantity = new_qty
        if user is not None:
            if hasattr(row, "updated_by"):
                row.updated_by = user
            if getattr(row, "pk", None) is None and hasattr(row, "created_by"):
                row.created_by = user
        row.full_clean()
        row.save(update_fields=["quantity", "updated_at", "updated_by"])
        return row

DEST_TYPES = (("warehouse", "Warehouse"), ("business", "Business"))

class StockMoveCreateForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.select_related("business").order_by("business__name", "name", "id"),
        widget=forms.Select(attrs={"class": "rounded-md border border-slate-300 px-2 py-2 w-full"})
    )
    source_warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.order_by("name", "id"),
        widget=forms.Select(attrs={"class": "rounded-md border border-slate-300 px-2 py-2 w-full"})
    )

    destination_type = forms.ChoiceField(
        choices=DEST_TYPES,
        widget=forms.RadioSelect(attrs={"class": "mr-2"})
    )

    dest_warehouse = forms.ModelChoiceField(
        required=False,
        queryset=Warehouse.objects.order_by("name", "id"),
        widget=forms.Select(attrs={"class": "rounded-md border border-slate-300 px-2 py-2 w-full"})
    )
    dest_business = forms.ModelChoiceField(
        required=False,
        queryset=Business.objects.order_by("name", "id"),
        widget=forms.Select(attrs={"class": "rounded-md border border-slate-300 px-2 py-2 w-full"})
    )

    quantity = forms.DecimalField(
        max_digits=18, decimal_places=6, min_value=Decimal("0.000001"),
        widget=forms.NumberInput(attrs={"step": "0.000001", "min": "0", "class": "rounded-md border border-slate-300 px-2 py-2 w-full"})
    )
    reference = forms.CharField(
        required=False, max_length=120,
        widget=forms.TextInput(attrs={"class": "rounded-md border border-slate-300 px-2 py-2 w-full"})
    )

    def clean(self):
        cleaned = super().clean()
        dest_type = cleaned.get("destination_type")
        src_wh = cleaned.get("source_warehouse")
        dst_wh = cleaned.get("dest_warehouse")
        dst_biz = cleaned.get("dest_business")
        product = cleaned.get("product")

        if dest_type not in {"warehouse", "business"}:
            raise ValidationError("Choose a valid destination type.")

        # Exactly one destination based on type
        if dest_type == "warehouse":
            if not dst_wh:
                raise ValidationError({"dest_warehouse": "Select a destination warehouse."})
            if src_wh and dst_wh and src_wh.pk == dst_wh.pk:
                raise ValidationError("Source and destination warehouse cannot be the same.")
            cleaned["source_business"] = None
            cleaned["dest_business"] = None
        else:
            if not dst_biz:
                raise ValidationError({"dest_business": "Select a destination business."})
            # Product.business must match destination business (your model clean() enforces it too)
            if product and product.business_id != dst_biz.id:
                raise ValidationError("Product’s business must match the destination business.")
            cleaned["dest_warehouse"] = None

        return cleaned

    def create_move(self, user=None) -> StockMove:
        """
        Create + immediately post the move.
        """
        data = self.cleaned_data
        move = StockMove(
            product=data["product"],
            source_warehouse=data["source_warehouse"],
            dest_warehouse=data.get("dest_warehouse") or None,
            dest_business=data.get("dest_business") or None,
            quantity=data["quantity"],
            reference=data.get("reference") or "",
            status=StockMove.Status.DRAFT,
            created_by=getattr(user, "pk", None) and user or None,
            updated_by=getattr(user, "pk", None) and user or None,
        )
        move.save()
        # Move posting enforces: one source & one dest, stock availability, business match, etc.
        move.post(user=user)
        return move
    


from django import forms
from django.core.exceptions import ValidationError

from .models import Party, BankAccount, Payment, Business


from django import forms
from django.core.exceptions import ValidationError

from .models import Party, BankAccount, Payment, Business

BASE_INPUT = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2"

class QuickReceiptForm(forms.Form):
    party_id = forms.IntegerField(widget=forms.HiddenInput(), required=False)

    party_name = forms.CharField(
        label="Customer or Vendor",
        widget=forms.TextInput(
            attrs={
                "class": f"{BASE_INPUT} party-input",
                "placeholder": "Type customer or vendor name",
                "autocomplete": "off",
            }
        ),
    )

    # NEW: Date field to allow backdating
    date = forms.DateField(
        label="Receipt Date",
        initial=timezone.now,
        widget=forms.DateInput(
            attrs={
                "class": f"{BASE_INPUT} bg-white",
                "type": "date",  # HTML5 date picker
            }
        ),
    )

    type = forms.ChoiceField(
        label="Type",
        choices=[
            ("cash", "Cash"),
            ("bank", "Bank Transfer"),
            ("cheque", "Cheque"),
        ],
        widget=forms.Select(
            attrs={
                "class": f"{BASE_INPUT} bg-white",
            }
        ),
    )

    amount = forms.DecimalField(
        label="Amount",
        min_value=0.01,
        decimal_places=2,
        max_digits=12,
        widget=forms.NumberInput(
            attrs={
                "class": f"{BASE_INPUT}",
                "step": "0.01",
            }
        ),
    )

    bank_account = forms.ModelChoiceField(
        queryset=BankAccount.objects.filter(is_active=True),
        required=False,
        label="Bank",
        widget=forms.Select(
            attrs={
                "class": f"{BASE_INPUT} bg-white",
            }
        ),
    )

    cheque_status = forms.ChoiceField(
        label="Cheque status",
        choices=Payment.ChequeStatus.choices,
        widget=forms.RadioSelect,
        required=False,
        initial=Payment.ChequeStatus.PENDING,
    )

    ref_no = forms.CharField(
        label="Ref No. (optional)",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": BASE_INPUT,
            }
        ),
    )

    note = forms.CharField(
        label="Note (optional)",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": BASE_INPUT,
                "rows": 2,
            }
        ),
    )

    def clean(self):
        cleaned = super().clean()
        party_id      = cleaned.get("party_id")
        amount        = cleaned.get("amount")
        method        = cleaned.get("type")
        bank          = cleaned.get("bank_account")
        cheque_status = cleaned.get("cheque_status")

        if not party_id:
            raise ValidationError("Please select a customer or vendor from suggestions.")

        try:
            party = Party.objects.get(pk=party_id)
        except Party.DoesNotExist:
            raise ValidationError("Selected customer or vendor does not exist.")

        if amount is not None and amount <= 0:
            self.add_error("amount", "Amount must be positive.")

        # bank transfer always needs a bank
        if method == "bank" and not bank:
            self.add_error("bank_account", "Bank is required for Bank Transfer.")

        # cheque rules
        if method == "cheque":
            if not cheque_status:
                self.add_error("cheque_status", "Please select cheque status.")
            else:
                if cheque_status == Payment.ChequeStatus.DEPOSITED and not bank:
                    self.add_error("bank_account", "Bank is required when cheque is deposited.")

        self.party = party
        return cleaned

    def _infer_business(self, user):
        party = self.party
        business = party.default_business
        if not business and hasattr(user, "staff_profile"):
            business = getattr(user.staff_profile, "business", None)
        if not business:
            raise ValidationError(
                "Could not determine business for this receipt. "
                "Please set default_business on Party or Staff."
            )
        return business

    def create_payment(self, user):
        party         = self.party
        method        = self.cleaned_data["type"]
        amount        = self.cleaned_data["amount"]
        payment_date  = self.cleaned_data["date"]  # <--- Using the date from the form
        bank_account  = self.cleaned_data.get("bank_account")
        ref_no        = self.cleaned_data.get("ref_no") or ""
        note          = self.cleaned_data.get("note") or ""
        cheque_status = self.cleaned_data.get("cheque_status")

        business = self._infer_business(user)

        if method == "cash":
            payment_method = Payment.PaymentMethod.CASH
            bank_account = None
        elif method == "bank":
            payment_method = Payment.PaymentMethod.BANK
        else:
            payment_method = Payment.PaymentMethod.CHEQUE

        payment = Payment(
            business=business,
            party=party,
            date=payment_date,  # <--- Backdated date applied here
            direction=Payment.IN,
            amount=amount,
            description=note,
            reference=ref_no,
            payment_method=payment_method,
            bank_account=bank_account,
            created_by=user,
            updated_by=user,
        )

        if method == "cheque":
            payment.cheque_status = cheque_status or Payment.ChequeStatus.PENDING

        payment.full_clean()
        payment.save()
        return payment

class CashOutForm(forms.Form):
    party_id = forms.IntegerField(widget=forms.HiddenInput(), required=False)

    party_name = forms.CharField(
        label="Payee (Customer or Vendor)",
        widget=forms.TextInput(
            attrs={
                "class": f"{BASE_INPUT} party-input",
                "placeholder": "Type customer or vendor name",
                "autocomplete": "off",
            }
        ),
    )

    date = forms.DateField(
        label="Payment Date",
        initial=timezone.now,
        widget=forms.DateInput(
            attrs={
                "class": f"{BASE_INPUT} bg-white",
                "type": "date",
            }
        ),
    )

    amount = forms.DecimalField(
        label="Amount",
        min_value=0.01,
        decimal_places=2,
        max_digits=12,
        widget=forms.NumberInput(
            attrs={
                "class": f"{BASE_INPUT}",
                "step": "0.01",
            }
        ),
    )

    override_cash_limit = forms.BooleanField(
        label="Override cash-in-hand limit",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-300"}),
        help_text="Check this to allow payment even if cash in hand is insufficient.",
    )

    ref_no = forms.CharField(
        label="Voucher / Ref No. (optional)",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": BASE_INPUT,
            }
        ),
    )

    note = forms.CharField(
        label="Narration / Note (optional)",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": BASE_INPUT,
                "rows": 2,
            }
        ),
    )

    def clean(self):
        cleaned = super().clean()
        party_id = cleaned.get("party_id")
        amount = cleaned.get("amount")
        override = cleaned.get("override_cash_limit")

        if not party_id:
            raise ValidationError("Please select a customer or vendor from suggestions.")

        try:
            self.party = Party.objects.get(pk=party_id)
        except Party.DoesNotExist:
            raise ValidationError("Selected party does not exist.")

        # Cash in hand validation
        if amount and not override:
            business = self._infer_business(None) # Pass None since we'll check it from party/staff
            if business:
                from .models import BusinessSummary
                summary = BusinessSummary.objects.filter(business=business).first()
                available = summary.cash_in_hand if summary else 0
                if amount > available:
                    raise ValidationError(
                        f"Insufficient Cash in Hand. Available: Rs. {available}. "
                        "Tick 'Override' if you are sure."
                    )
        
        return cleaned

    def _infer_business(self, user):
        # If user is provided, we can look at their staff profile
        # Otherwise, fall back to party's default business
        business = None
        if user and hasattr(user, "staff_profile"):
            business = getattr(user.staff_profile, "business", None)
        
        if not business and hasattr(self, 'party'):
            business = self.party.default_business
            
        if not business and user:
            # Last resort: check UserSettings for default sale business
            from .models import UserSettings
            settings = UserSettings.objects.filter(user=user).first()
            if settings:
                business = settings.default_sale_business
                
        return business

    def create_payment(self, user):
        party = self.party
        amount = self.cleaned_data["amount"]
        payment_date = self.cleaned_data["date"]
        ref_no = self.cleaned_data.get("ref_no") or ""
        note = self.cleaned_data.get("note") or ""
        business = self._infer_business(user)

        if not business:
             raise ValidationError("Could not determine business for this payment.")

        payment = Payment(
            business=business,
            party=party,
            date=payment_date,
            direction=Payment.OUT,
            amount=amount,
            description=note,
            reference=ref_no,
            payment_method=Payment.PaymentMethod.CASH, # Cash Out is always CASH source here
            created_by=user,
            updated_by=user,
        )
        payment.full_clean()
        payment.save()
        return payment
