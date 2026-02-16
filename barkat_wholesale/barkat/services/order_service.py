from datetime import datetime, date
from decimal import Decimal
from django.db import transaction
from django.db.models import F
from django.core.exceptions import ValidationError
from django.contrib import messages
from barkat.models import (
    Product, Payment, SalesOrder, SalesOrderItem, 
    PurchaseOrder, PurchaseOrderItem, Expense, 
    PurchaseOrderPayment, Business
)
from django.utils import timezone

class OrderService:
    @staticmethod
    @transaction.atomic
    def validate_and_adjust_stock(items_data, reverse=False):
        """
        Validates stock availability and adjusts levels.
        items_data: list of dicts {'product_id': id, 'quantity': qty, 'size_per_unit': size}
        reverse: if True, adds stock back (e.g., on cancellation or update reversal)
        """
        requested = {}
        for item in items_data:
            pid = item['product_id']
            base_qty = Decimal(str(item['quantity'])) * Decimal(str(item.get('size_per_unit', 1)))
            if base_qty <= 0:
                continue
            requested[pid] = requested.get(pid, Decimal("0")) + base_qty

        if not requested:
            return True, {}

        # Lock products
        products = Product.objects.select_for_update().filter(id__in=requested.keys(), is_deleted=False)
        stock_map = {p.id: p for p in products}
        
        errors = {}
        for pid, need in requested.items():
            product = stock_map.get(pid)
            if not product:
                errors[pid] = "Product not found."
                continue
            
            if not reverse:
                if (product.stock_qty or 0) < need:
                    errors[pid] = f"Insufficient stock for {product.name}. Available: {product.stock_qty}, Requested: {need}."
                else:
                    product.stock_qty = (product.stock_qty or 0) - need
            else:
                product.stock_qty = (product.stock_qty or 0) + need
            
            product.save(update_fields=['stock_qty', 'updated_at'])
            
        if errors and not reverse:
            return False, errors
        return True, {}

    @staticmethod
    @transaction.atomic
    def create_sales_order(user, business, customer_data, items_data, payment_data=None):
        """
        Centralized logic to create a Sales Order with items and optional payment.
        """
        # 1. Validate Stock
        success, errors = OrderService.validate_and_adjust_stock(items_data)
        if not success:
            raise ValidationError(errors)

        # 2. Create Order
        order = SalesOrder.objects.create(
            business=business,
            customer=customer_data.get('customer'),
            customer_name=customer_data.get('customer_name', ''),
            customer_phone=customer_data.get('customer_phone', ''),
            customer_address=customer_data.get('customer_address', ''),
            created_by=user,
            updated_by=user,
            status=SalesOrder.Status.OPEN
        )

        # 3. Create Items
        for item in items_data:
            SalesOrderItem.objects.create(
                sales_order=order,
                product_id=item['product_id'],
                quantity=item['quantity'],
                price=item['price'],
                uom_id=item.get('uom_id'),
                size_per_unit=item.get('size_per_unit', 1)
            )

        order.recompute_totals()
        order.save()

        # 4. Handle Payment
        if payment_data and payment_data.get('amount', 0) > 0:
            OrderService.apply_order_payment(order, payment_data, user)

        return order

    @staticmethod
    def apply_order_payment(order, payment_data, user):
        """
        Creates a Payment and applies it to the order.
        """
        method = payment_data.get('method')
        amount = Decimal(str(payment_data.get('amount', 0)))
        
        payment = Payment.objects.create(
            business=order.business,
            party=order.customer or OrderService._get_walkin_party(order.business),
            date=payment_data.get('date', timezone.now().date()),
            amount=amount,
            direction=Payment.IN,
            payment_method=method,
            payment_source='bank' if method in ('bank', 'card') else 'cash',
            bank_account=payment_data.get('bank_account'),
            created_by=user,
            updated_by=user
        )

        available = order.balance_due
        applied_amount = min(amount, available) if available > 0 else Decimal("0.00")

        if applied_amount > 0:
            order.apply_receipt(payment, applied_amount)
            order.recompute_totals()
            if order.paid_total >= order.net_total and order.net_total > 0:
                order.status = SalesOrder.Status.FULFILLED
            order.save()
        
        return payment

    @staticmethod
    def _get_walkin_party(business):
        from barkat.models import Party
        return Party.objects.filter(
            business=business, 
            display_name__icontains="Walk-in", 
            is_deleted=False
        ).first()

    @staticmethod
    @transaction.atomic
    def process_sales_order_form(user, form, formset, is_update=False):
        """
        Handles the core logic for SalesOrder Create/Update views.
        Reduces 200+ lines of view logic into a single service call.
        """
        order = form.save(commit=False)
        if not is_update:
            # Creation specific logic (e.g. initial status)
            order.created_by = user
            order.status = SalesOrder.Status.OPEN
            
            # Handle order_date timezone
            order_date = form.cleaned_data.get("order_date")
            if order_date:
                if isinstance(order_date, datetime):
                    order.created_at = timezone.make_aware(order_date) if timezone.is_naive(order_date) else order_date
                elif isinstance(order_date, date):
                    order.created_at = timezone.make_aware(datetime.combine(order_date, datetime.min.time()))
            else:
                order.created_at = timezone.now()
        
        order.updated_by = user
        business = order.business

        # Walk-in customer logic
        customer = form.cleaned_data.get("customer")
        cname = (form.cleaned_data.get("customer_name") or "").strip()
        if not customer and not cname:
            walkin = OrderService._get_walkin_party(business)
            if walkin:
                order.customer = walkin
                order.customer_name = walkin.display_name
                order.customer_phone = walkin.phone or ""
                order.customer_address = walkin.address or ""
        else:
            order.customer = customer
            if cname: order.customer_name = cname

        # Calculate stock changes
        stock_changes = {}
        if is_update:
            # Reversal logic for update
            db_items = {
                it.id: (it.product_id, it.quantity, it.size_per_unit or Decimal("1")) 
                for it in order.items.all()
            }
            for f in formset.forms:
                if not f.cleaned_data: continue
                instance_id = f.instance.id
                new_pid = f.cleaned_data.get('product').id if f.cleaned_data.get('product') else None
                new_qty = f.cleaned_data.get('quantity') or Decimal('0')
                new_size = f.cleaned_data.get('size_per_unit') or Decimal('1')
                if instance_id in db_items:
                    old_pid, old_qty, old_size = db_items[instance_id]
                    old_base = old_qty * old_size
                    new_base = new_qty * new_size
                    if f.cleaned_data.get('DELETE'):
                        stock_changes[old_pid] = stock_changes.get(old_pid, Decimal('0')) + old_base
                    elif new_pid != old_pid:
                        stock_changes[old_pid] = stock_changes.get(old_pid, Decimal('0')) + old_base
                        if new_pid: stock_changes[new_pid] = stock_changes.get(new_pid, Decimal('0')) - new_base
                    else:
                        stock_changes[old_pid] = stock_changes.get(old_pid, Decimal('0')) + (old_base - new_base)
                elif not f.cleaned_data.get('DELETE') and new_pid:
                    stock_changes[new_pid] = stock_changes.get(new_pid, Decimal('0')) - (new_qty * new_size)
        else:
            # Deduct logic for create
            for f in formset.forms:
                if not f.cleaned_data or f.cleaned_data.get('DELETE'): continue
                pid = f.cleaned_data.get('product').id
                qty = f.cleaned_data.get('quantity') or Decimal('0')
                size = f.cleaned_data.get('size_per_unit') or Decimal('1')
                stock_changes[pid] = stock_changes.get(pid, Decimal('0')) - (qty * size)

        # Apply stock changes
        for pid, diff in stock_changes.items():
            if diff != 0:
                Product.objects.filter(id=pid).update(
                    stock_qty=F('stock_qty') + diff,
                    updated_at=timezone.now(),
                    updated_by=user
                )

        order.save()

        # Save items
        for item_form in formset:
            if item_form.cleaned_data and not item_form.cleaned_data.get('DELETE'):
                item = item_form.save(commit=False)
                item.sales_order = order
                if not item.uom_id: item.uom = item.product.uom
                item.size_per_unit = item.size_per_unit or Decimal("1.000000")
                item.save()
        formset.save()

        order.recompute_totals()
        
        # Payment handling
        method = form.cleaned_data.get("receipt_method")
        amount = form.cleaned_data.get("received_amount") or Decimal("0.00")
        if is_update and method in ("cash", "bank", "card"):
            # Clean up old payments on update if new payment info provided
            for app in order.receipt_applications.all():
                pay = app.payment
                app.delete()
                pay.delete()

        if method in ("cash", "bank", "card") and amount > 0:
            from datetime import date as py_date
            # Handle pay_date
            order_date = form.cleaned_data.get("order_date")
            if order_date:
                pay_date = order_date.date() if isinstance(order_date, datetime) else order_date
            else:
                pay_date = timezone.localdate(order.created_at)
            
            OrderService.apply_order_payment(order, {
                'method': method,
                'amount': amount,
                'date': pay_date,
                'bank_account': form.cleaned_data.get("bank_account")
            }, user)

        order.recompute_totals()
        if order.paid_total >= order.net_total and order.net_total > 0:
            order.status = SalesOrder.Status.FULFILLED
        elif order.status != SalesOrder.Status.CANCELLED:
            order.status = SalesOrder.Status.OPEN
        order.save()

        return order

    @staticmethod
    @transaction.atomic
    def process_purchase_order_form(user, form, formset, expense_formset, is_update=False):
        """
        Handles the core logic for PurchaseOrder Create/Update views.
        Centralizes PO saving, item management, expense handling (including instant payments),
        and stock adjustments based on status.
        """
        po = form.save(commit=False)
        old_status = None
        old_qty_by_product = {}

        if is_update:
            # Snapshot for stock delta calculation
            po_db = PurchaseOrder.objects.select_for_update().prefetch_related("items").get(pk=po.pk)
            old_status = (po_db.status or "").lower()
            for it in po_db.items.all():
                if it.product_id:
                    base_qty = (it.quantity or Decimal("0")) * (it.size_per_unit or Decimal("1"))
                    if base_qty > 0:
                        old_qty_by_product[it.product_id] = old_qty_by_product.get(it.product_id, Decimal("0")) + base_qty
            po.updated_by = user
        else:
            po.created_by = user
            po.updated_by = user
            # Handle po_date -> created_at
            po_date = form.cleaned_data.get("po_date")
            if po_date:
                po.created_at = timezone.make_aware(datetime.combine(po_date, datetime.min.time())) if timezone.is_naive(datetime.now()) else datetime.combine(po_date, datetime.min.time())
            else:
                po.created_at = timezone.now()

        # Business assignment (especially for CreateView)
        bid = form.cleaned_data.get("business")
        if bid:
            po.business = bid if isinstance(bid, Business) else Business.objects.get(pk=bid)

        po.save()

        # 1. Save Items
        for item_form in formset:
            if item_form.cleaned_data and not item_form.cleaned_data.get('DELETE'):
                item = item_form.save(commit=False)
                item.purchase_order = po
                if not item.uom_id: item.uom = item.product.uom
                item.size_per_unit = item.size_per_unit or Decimal("1.000000")
                
                # Handle sale price conversion (bulk -> lower unit)
                sale_price = item_form.cleaned_data.get('sale_price')
                if sale_price is not None and sale_price > 0:
                    prod = item.product
                    if (prod.bulk_uom_id and item.uom_id == prod.bulk_uom_id and 
                        item.size_per_unit and item.size_per_unit > 1):
                        lower_price = sale_price / item.size_per_unit
                        Product.objects.filter(pk=prod.pk).update(sale_price=lower_price)
                    else:
                        Product.objects.filter(pk=prod.pk).update(sale_price=sale_price)
                item.save()
        
        if is_update:
            for deleted_item in formset.deleted_objects:
                deleted_item.delete()
        formset.save_m2m()

        # 2. Stock Update Logic (Delta based)
        new_status = (po.status or "").lower()
        new_qty_by_product = {}
        for it in po.items.all():
            if it.product_id:
                base_qty = (it.quantity or Decimal("0")) * (it.size_per_unit or Decimal("1"))
                if base_qty > 0:
                    new_qty_by_product[it.product_id] = new_qty_by_product.get(it.product_id, Decimal("0")) + base_qty

        all_pids = set(old_qty_by_product.keys()) | set(new_qty_by_product.keys())
        for pid in all_pids:
            old_effect = old_qty_by_product.get(pid, Decimal("0")) if old_status == "received" else Decimal("0")
            new_effect = new_qty_by_product.get(pid, Decimal("0")) if new_status == "received" else Decimal("0")
            delta = new_effect - old_effect
            if delta != 0:
                Product.objects.filter(pk=pid).update(stock_qty=F("stock_qty") + delta)
                # If received, update purchase price too
                if new_status == "received":
                    # Get the specific item's landing price
                    item = po.items.filter(product_id=pid).first()
                    if item:
                        price = item.landing_unit_price or item.unit_price
                        if price: Product.objects.filter(pk=pid).update(purchase_price=price)

        # 3. Save Expenses
        expenses = expense_formset.save(commit=False)
        for exp in expenses:
            exp.purchase_order = po
            exp.business = po.business
            exp.created_by = user if not exp.pk else exp.created_by
            exp.updated_by = user
            exp.save()

            # Instant payment for expense
            if exp.is_paid and not exp.payment:
                pay_method = exp.payment_source # 'cash' / 'bank'
                payment = Payment.objects.create(
                    business=po.business,
                    date=po.created_at.date(),
                    party=po.supplier,
                    amount=exp.amount,
                    description=f"Instant payment for PO #{po.id} expense: {exp.get_category_display()}",
                    reference=f"PO-{po.id}-EXP",
                    payment_source=Payment.CASH if pay_method == "cash" else Payment.BANK,
                    payment_method="bank" if pay_method == "bank" else "cash",
                    direction=Payment.OUT,
                    created_by=user,
                    updated_by=user,
                    bank_account=exp.bank_account if pay_method == "bank" else None
                )
                exp.payment = payment
                exp.save(update_fields=["payment", "updated_at", "updated_by"])
                po.apply_payment(payment, exp.amount)

        if is_update:
            for deleted_exp in expense_formset.deleted_objects:
                deleted_exp.delete()

        po.distribute_expenses()
        po.recompute_totals()
        po.save()

        # 4. Handle PO Main Payment
        paid = (form.cleaned_data.get("paid_amount") or Decimal("0.00")).quantize(Decimal("0.01"))
        method = form.cleaned_data.get("payment_method") or "none"
        if paid > 0:
            pay_source = None
            if method == "cash": pay_source = Payment.CASH
            elif method in ("bank", "cheque"): pay_source = Payment.BANK
            
            if pay_source:
                payment = Payment.objects.create(
                    business=po.business,
                    date=po.created_at.date(),
                    party=po.supplier,
                    amount=paid,
                    description=f"Payment for PO #{po.id}",
                    reference=f"PO-{po.id}",
                    payment_source=pay_source,
                    payment_method=method,
                    direction=Payment.OUT,
                    created_by=user,
                    updated_by=user,
                    bank_account=form.cleaned_data.get("bank_account") if method in ("bank", "cheque") else None
                )
                po.apply_payment(payment, paid)

        po.recompute_totals()
        po.save()
        return po
