# barkat/pos_print_views.py
from __future__ import annotations
import sys
from pathlib import Path
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
from .models import CashFlow
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse, HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import ValidationError

from .forms import SalesOrderForm, SalesOrderItemFormSet
from .models import Business, SalesOrder, SalesOrderItem, Product, Payment, Party
from .utils.receipt_render import render_receipt_bitmap
from .utils.pos_print import raw_print_bitmap, PosPrintError
from .ledger_views import _compute_party_balance

# -------- Settings / paths ----------------------------------------------------


TMP_DIR: Path = Path(
    getattr(settings, "RECEIPT_TMP_DIR", Path(settings.BASE_DIR) / "tmp_receipts")
).resolve()
TMP_DIR.mkdir(parents=True, exist_ok=True)

def _q2(v) -> Decimal:
    """Quantize to 2 decimal places to match UpdateView logic."""
    try:
        return Decimal(str(v or "0")).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")

def _get_walkin_party(business):
    """Reuse existing Walk-in-Customer logic."""
    qs = Party.objects.filter(
        is_active=True,
        is_deleted=False,
        display_name__iexact="Walk-in-Customer",
    )
    biz_id = getattr(business, "id", None) or getattr(business, "pk", None)
    if biz_id is None and str(business).isdigit():
        biz_id = int(business)
    if biz_id:
        p = qs.filter(default_business_id=biz_id).first()
        if p: return p
    return qs.first()

def _model_has_field(model, field_name: str) -> bool:
    return any(
        getattr(f, "name", None) == field_name
        and getattr(f, "concrete", False)
        for f in model._meta.get_fields()
    )

def ensure_party_for_receipt(*, business, customer=None, customer_name="", customer_phone=""):
    if customer: return customer
    search_name = (customer_name or "Walk-in-Customer").strip()
    qs = Party.objects.all()
    if _model_has_field(Party, "default_business") and business:
        qs = qs.filter(default_business=business)
    if customer_phone:
        found = qs.filter(phone=customer_phone).first()
        if found: return found
    found = qs.filter(display_name__iexact=search_name).first()
    if found: return found
    
    data = {"display_name": search_name, "phone": customer_phone or "", "type": "CUSTOMER"}
    if business: data["default_business"] = business
    return Party.objects.create(**data)

def _collect_items(order: SalesOrder):
    return list(SalesOrderItem.objects.filter(sales_order=order).select_related("product", "uom", "product__uom", "product__bulk_uom"))

def _width_px_from_kind(width_kind: str | None) -> int:
    wk = (width_kind or "80mm").strip().lower()
    return 576 if ("80" in wk or wk == "80mm") else 384

def _resolve_printer_name(business: Business) -> str:
    name = (business.pos_printer_name or "").strip()
    if not name:
        raise PosPrintError("No POS printer configured for this business.")
    return name

# -------- Views ---------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class DebugListPrintersView(View):
    """Optional helper to list printers on Windows with pywin32 installed."""
    def post(self, request: HttpRequest):
        info = {"ok": True, "platform": sys.platform, "printers": []}
        try:
            import win32print  # type: ignore
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            for p in win32print.EnumPrinters(flags):
                info["printers"].append({"name": str(p[2])})
            return JsonResponse(info)
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=500)


@method_decorator(csrf_exempt, name="dispatch")
class PrintSalesOrderReceiptView(View):
    def post(self, request: HttpRequest, pk: int):
        try:
            business_id = request.GET.get("business")
            if not business_id:
                return JsonResponse({"ok": False, "error": "business param is required"}, status=400)

            business = get_object_or_404(Business, pk=int(business_id))
            order = get_object_or_404(SalesOrder, pk=pk)

            width_px = _width_px_from_kind(request.GET.get("width_kind"))
            items = _collect_items(order)

            bmp_path = render_receipt_bitmap(
                business=business, order=order, items=items,
                width_px=width_px, out_dir=TMP_DIR,
            )

            printer_name = _resolve_printer_name(business)
            raw_print_bitmap(printer_name=printer_name, bmp_path=bmp_path, width_px=width_px)

            return JsonResponse({"ok": True, "path": str(bmp_path), "printer": printer_name})
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=500)


@method_decorator(csrf_exempt, name="dispatch")
class SaveAndPrintOrderView(View):
    def post(self, request: HttpRequest, *args, **kwargs):
        try:
            business_id = request.GET.get("business") or request.POST.get("business") or request.POST.get("business_id")
            if not business_id:
                return JsonResponse({"ok": False, "error": "Missing ?business=<id>."}, status=400)

            business = get_object_or_404(Business, id=business_id)
            so_instance = None
            is_edit = bool(request.POST.get("id"))
            if is_edit:
                so_instance = get_object_or_404(SalesOrder, id=request.POST.get("id"))

            form = SalesOrderForm(request.POST or None, instance=so_instance, business=business)
            formset = SalesOrderItemFormSet(request.POST or None, instance=(so_instance or SalesOrder()), form_kwargs={"business": business})

            if not form.is_valid() or not formset.is_valid():
                return JsonResponse({
                    "ok": False, 
                    "error": "Validation failed", 
                    "form_errors": form.errors,
                    "formset_errors": formset.errors
                }, status=400)

            # Validate at least one product
            valid_items_count = 0
            for f in formset.forms:
                cd = getattr(f, "cleaned_data", None)
                if not cd or cd.get("DELETE"):
                    continue
                prod = cd.get("product")
                qty = cd.get("quantity") or Decimal("0")
                if prod and qty > 0:
                    valid_items_count += 1

            if valid_items_count == 0:
                return JsonResponse({"ok": False, "error": "Sales Order must have at least one product item."}, status=400)

            # --- 1. Stock check with UOM support (convert to base unit) ---
            requested = {}
            row_map = {}
            for f in formset.forms:
                cd = getattr(f, "cleaned_data", None)
                if not cd or cd.get("DELETE"):
                    continue
                prod = cd.get("product")
                qty = cd.get("quantity") or Decimal("0")
                size = cd.get("size_per_unit") or Decimal("1")
                
                if not prod or qty <= 0:
                    continue
                    
                # Convert to base unit for stock check
                base_qty = qty * size
                requested[prod.id] = requested.get(prod.id, Decimal("0")) + base_qty
                row_map.setdefault(prod.id, []).append(f)

            # For edit mode: calculate old quantities with UOM
            old_requested = {}
            if so_instance:
                for it in so_instance.items.all():
                    old_size = it.size_per_unit or Decimal("1")
                    old_base = (it.quantity or Decimal("0")) * old_size
                    old_requested[it.product_id] = old_requested.get(it.product_id, Decimal("0")) + old_base

            # Check stock availability
            if requested:
                prods = (
                    Product.objects
                    .select_for_update()
                    .filter(id__in=requested.keys(), is_deleted=False)
                )
                stock_map = {p.id: (p.stock_qty or Decimal("0")) for p in prods}

                errors = []
                for pid, need in requested.items():
                    have = stock_map.get(pid, Decimal("0"))
                    # For edit mode, add back old quantities
                    if is_edit:
                        have = have + old_requested.get(pid, Decimal("0"))
                    if need > have:
                        prod_name = prods.filter(id=pid).first()
                        prod_name = prod_name.name if prod_name else f"Product #{pid}"
                        errors.append(f"{prod_name}: Only {have} in stock. You requested {need}.")
                
                if errors:
                    return JsonResponse({"ok": False, "error": "Stock error", "messages": errors}, status=400)

            # Calculate stock delta (for edit mode)
            stock_changes = {}
            if is_edit:
                for pid in set(requested.keys()) | set(old_requested.keys()):
                    new_base = requested.get(pid, Decimal("0"))
                    old_base = old_requested.get(pid, Decimal("0"))
                    delta = old_base - new_base
                    if delta != 0:
                        stock_changes[pid] = delta
            else:
                # For new orders, all requested quantities need to be deducted
                for pid, need in requested.items():
                    stock_changes[pid] = -need

            def D(val, default="0"):
                try:
                    return Decimal(str(val if val not in (None, "") else default))
                except (InvalidOperation, ValueError):
                    return Decimal(str(default))

            with transaction.atomic():
                # --- 2. Save Order ---
                order = form.save(commit=False)
                order.business = business

                # Extract order_date FIRST (needed for both create and edit modes)
                order_date = form.cleaned_data.get("order_date")

                # Set created_at ONLY for new orders (never modify on edit)
                if not is_edit:
                    if order_date:
                        if isinstance(order_date, datetime):
                            order.created_at = timezone.make_aware(order_date) if not timezone.is_aware(order_date) else order_date
                        else:
                            order.created_at = timezone.now()
                    else:
                        order.created_at = timezone.now()
                # For edit: created_at remains unchanged (immutable after creation)

                # Customer handling - identical to CreateView/UpdateView
                customer = form.cleaned_data.get("customer")
                cname = (form.cleaned_data.get("customer_name") or "").strip()

                # Walk-in customer logic
                if not customer and not cname:
                    walkin = _get_walkin_party(business)
                    if walkin:
                        order.customer = walkin
                        order.customer_name = walkin.display_name
                        order.customer_phone = walkin.phone or ""
                        order.customer_address = walkin.address or ""
                    else:
                        order.customer = None
                        order.customer_name = "Walk-in Customer"
                        order.customer_phone = ""
                        order.customer_address = ""
                else:
                    order.customer = customer
                    if cname:
                        order.customer_name = cname

                if request.user.is_authenticated:
                    if not is_edit:
                        order.created_by = request.user
                    order.updated_by = request.user
                order.save()

                # Save items with UOM support
                formset.instance = order
                for item_form in formset:
                    if item_form.cleaned_data and not item_form.cleaned_data.get('DELETE'):
                        item = item_form.save(commit=False)
                        item.sales_order = order
                        
                        # Ensure uom and size_per_unit are set
                        if not item.uom_id:
                            item.uom = item.product.uom
                        if not item.size_per_unit:
                            item.size_per_unit = Decimal("1.000000")
                            
                        item.save()

                # --- 3. Apply Stock Changes ---
                for pid, qty_to_change in stock_changes.items():
                    if qty_to_change != 0:
                        Product.objects.filter(id=pid).update(stock_qty=F("stock_qty") + qty_to_change)

                # Recompute totals before handling payments
                order.recompute_totals()
                
                # Set initial status
                if not is_edit:
                    order.status = SalesOrder.Status.OPEN
                order.save()

                # --- 4. Receipt/Payment Handling ---
                method = form.cleaned_data.get("receipt_method") or "none"
                amount = form.cleaned_data.get("received_amount") or Decimal("0.00")
                bank = form.cleaned_data.get("bank_account")
                
                # Extract date from order_date for payment (order_date already extracted above)
                if order_date:
                    if isinstance(order_date, datetime):
                        pay_date = timezone.localdate(order_date) if timezone.is_aware(order_date) else order_date.date()
                    elif isinstance(order_date, date):
                        pay_date = order_date
                    else:
                        pay_date = timezone.localdate()
                else:
                    # Fallback: use order's created_at date if available, otherwise today
                    if order.created_at:
                        pay_date = timezone.localdate(order.created_at) if timezone.is_aware(order.created_at) else order.created_at.date()
                    else:
                        pay_date = timezone.localdate()

                if method in ("cash", "bank", "card") and amount and amount > 0:
                    # Clean up old applications if updating
                    if is_edit:
                        for app in order.receipt_applications.all():
                            pay_to_del = app.payment
                            if hasattr(pay_to_del, 'cashflow') and pay_to_del.cashflow:
                                pay_to_del.cashflow.delete()
                            app.delete()
                            pay_to_del.delete()

                    party = order.customer or _get_walkin_party(business)

                    if party:
                        # Card and Bank both go to bank ledger
                        payment_source_value = "bank" if method in ("bank", "card") else "cash"

                        payment_kwargs = {
                            "business": business,
                            "party": party,
                            "date": pay_date,
                            "amount": amount,
                            "payment_source": payment_source_value,
                        }

                        if request.user.is_authenticated:
                            payment_kwargs["created_by"] = request.user
                            payment_kwargs["updated_by"] = request.user

                        if _model_has_field(Payment, "direction"):
                            payment_kwargs["direction"] = Payment.IN

                        if _model_has_field(Payment, "payment_method"):
                            payment_kwargs["payment_method"] = method

                        # Bank and Card both require bank_account
                        if method in ("bank", "card") and _model_has_field(Payment, "bank_account") and bank:
                            payment_kwargs["bank_account"] = bank

                        pay = Payment.objects.create(**payment_kwargs)

                        available = _q2(order.balance_due)
                        applied_amount = _q2(amount)
                        
                        if available <= 0:
                            applied_amount = Decimal("0.00")
                        elif applied_amount > available:
                            applied_amount = available

                        if applied_amount > 0:
                            try:
                                order.apply_receipt(pay, applied_amount)
                                order.recompute_totals()
                                # Auto-update status to fulfilled if fully paid
                                if order.paid_total >= order.net_total and order.net_total > Decimal("0.00"):
                                    order.status = SalesOrder.Status.FULFILLED
                                else:
                                    # If not fully paid, ensure status is OPEN (unless already cancelled)
                                    if order.status != SalesOrder.Status.CANCELLED:
                                        order.status = SalesOrder.Status.OPEN
                                if request.user.is_authenticated:
                                    order.updated_by = request.user
                                order.save()
                            except ValidationError as ve:
                                return JsonResponse({"ok": False, "error": f"Payment validation error: {ve}"}, status=400)

                # Final status check and save
                order.recompute_totals()
                if order.paid_total >= order.net_total and order.net_total > Decimal("0.00"):
                    order.status = SalesOrder.Status.FULFILLED
                elif order.status != SalesOrder.Status.CANCELLED:
                    order.status = SalesOrder.Status.OPEN
                order.save()

            # --- 5. Printing ---
            # Explicitly refresh from DB to get the calculated values
            order.refresh_from_db()
            # Attach form receipt_method / received_amount / bank_account for receipt render (e.g. on_credit → 0)
            order.receipt_method = form.cleaned_data.get("receipt_method") or "cash"
            order.received_amount = form.cleaned_data.get("received_amount") or Decimal("0.00")
            order.bank_account = form.cleaned_data.get("bank_account")

            width_px = _width_px_from_kind(request.GET.get("width_kind"))
            items = _collect_items(order)
            bmp_path = render_receipt_bitmap(business=business, order=order, items=items, width_px=width_px, out_dir=TMP_DIR)
            raw_print_bitmap(printer_name=_resolve_printer_name(business), bmp_path=bmp_path, width_px=width_px)

            return JsonResponse({"ok": True, "order_id": order.id, "path": str(bmp_path)})

        except Exception as e:
            import traceback
            return JsonResponse({"ok": False, "error": f"Unexpected: {e}", "traceback": traceback.format_exc()}, status=500)
