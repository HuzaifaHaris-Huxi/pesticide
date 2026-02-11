# erp/admin.py
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from django import forms
from django.contrib import admin
from .models import Business

from .models import Business, Staff

@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "phone", "email", "is_active")
    search_fields = ("code", "name", "legal_name", "phone", "email")
    list_filter = ("is_active",)
    ordering = ("code",)

@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "business",
        "role",
        "phone",
        "cnic",
        "has_software_access",
        "linked_username",
        "linked_user_active",
        "joined_on",
    )
    list_select_related = ("business", "user")
    list_filter = (
        "business",
        "role",
        "has_software_access",
        "access_sales",
        "access_inventory",
        "access_accounts",
        ("joined_on", admin.DateFieldListFilter),
    )
    search_fields = (
        "full_name",
        "phone",
        "cnic",
        "address",
        "user__username",
        "user__email",
    )
    autocomplete_fields = ("business", "user")
    ordering = ("business__code", "full_name")
    readonly_fields = ("created_at", "updated_at", "created_by", "updated_by")

    fieldsets = (
        ("Identity", {
            "fields": ("business", "full_name", "role", "phone", "cnic", "address"),
        }),
        ("Software Access", {
            "fields": (
                "has_software_access",
                "user",
                "access_sales",
                "access_inventory",
                "access_accounts",
            ),
            "description": "Link a Django user to enable login for this staff member.",
        }),
        ("HR & Payroll", {
            "fields": ("joined_on", "salary_start", "monthly_salary"),
        }),
        ("System", {
            "fields": ("created_at", "updated_at", "created_by", "updated_by"),
        }),
    )

    actions = ("action_provision_user", "action_revoke_access", "action_deactivate_user")

    # ---------- Display helpers ----------
    @admin.display(description="Username", ordering="user__username")
    def linked_username(self, obj: Staff):
        return obj.user.username if obj.user_id else "—"

    @admin.display(boolean=True, description="User Active", ordering="user__is_active")
    def linked_user_active(self, obj: Staff):
        return bool(obj.user.is_active) if obj.user_id else False

    # ---------- Save hooks ----------
    def save_model(self, request, obj: Staff, form, change):
        # track who created/updated (fits your mixin)
        if not change and not obj.created_by_id:
            obj.created_by = request.user
        obj.updated_by = request.user

        # Let model-level validation run
        obj.full_clean()
        super().save_model(request, obj, form, change)

    # ---------- Admin actions ----------
    def action_provision_user(self, request, queryset):
        """
        Creates a Django User for each selected staff that (a) has software access enabled
        or we enable it here, and (b) does not already have a linked user.
        Username is auto-generated from business code and full name.
        Password is left unusable; set/reset it from the User admin.
        """
        User = get_user_model()
        created = 0
        skipped = 0

        for staff in queryset.select_related("business", "user"):
            if staff.user_id:
                skipped += 1
                continue

            # Make sure software access is on
            if not staff.has_software_access:
                staff.has_software_access = True

            # Generate a unique username
            base = slugify(f"{staff.business.code}-{staff.full_name}")[:25] or "user"
            username = base
            i = 1
            while User.objects.filter(username=username).exists():
                suffix = f"-{i}"
                username = (base[: (25 - len(suffix))] + suffix)
                i += 1

            user = User(username=username, email="")
            user.set_unusable_password()
            user.is_active = True
            user.save()

            staff.user = user
            # do not recurse into save_model again; update minimal fields
            staff.save(update_fields=["user", "has_software_access", "updated_at", "updated_by"])
            created += 1

        if created:
            self.message_user(
                request,
                f"Provisioned {created} user(s). Set passwords from the User admin.",
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} staff member(s) already linked to a user.",
                level=messages.WARNING,
            )

    action_provision_user.short_description = "Provision login user for selected staff"

    def action_revoke_access(self, request, queryset):
        """
        Turns off software access and unlinks the user (keeps the User account).
        """
        updated = 0
        for staff in queryset.select_related("user"):
            if staff.has_software_access or staff.user_id:
                staff.has_software_access = False
                staff.save(update_fields=["has_software_access", "updated_at", "updated_by"])
                updated += 1
        self.message_user(request, f"Revoked access for {updated} staff.", level=messages.SUCCESS)

    action_revoke_access.short_description = "Revoke software access (keep User account)"

    def action_deactivate_user(self, request, queryset):
        """
        Deactivates the linked Django User (if any). Staff record remains.
        """
        deactivated = 0
        for staff in queryset.select_related("user"):
            if staff.user_id and staff.user.is_active:
                staff.user.is_active = False
                staff.user.save(update_fields=["is_active"])
                deactivated += 1
        self.message_user(request, f"Deactivated {deactivated} linked user(s).", level=messages.SUCCESS)

    action_deactivate_user.short_description = "Deactivate linked User account(s)"


# barkat/admin.py

try:
    import win32print
except Exception:
    win32print = None

def _installed_printers():
    if not win32print:
        return []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [p[2] for p in win32print.EnumPrinters(flags)]

class BusinessAdminForm(forms.ModelForm):
    class Meta:
        model = Business
        fields = "__all__"

    def clean_pos_printer_name(self):
        name = (self.cleaned_data.get("pos_printer_name") or "").strip()
        if not name:
            return name
        printers = _installed_printers()
        if printers and name not in printers:
            raise forms.ValidationError(
                f"'{name}' is not an installed printer. Installed: {', '.join(printers)}"
            )
        return name

class BusinessAdmin(admin.ModelAdmin):
    form = BusinessAdminForm
    list_display = ("code", "name", "pos_printer_name")
