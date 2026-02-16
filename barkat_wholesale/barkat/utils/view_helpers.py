from decimal import Decimal, InvalidOperation
from django.db.models import (
    F, Q, Sum, Value as V, 
    ExpressionWrapper, DecimalField
)
from django.db.models.functions import Coalesce
from django.templatetags.static import static
from django.conf import settings
from pathlib import Path
from barkat.models import Product, Party, Business

def _selected_business(request):
    """Pick business by ?business=ID or default to the first one."""
    biz_id = request.GET.get("business") or request.session.get("active_business_id")
    if biz_id:
        return Business.objects.filter(pk=biz_id, is_active=True, is_deleted=False).first()
    return Business.objects.filter(is_active=True, is_deleted=False).first()

def _product_image_url(p):
    """
    Return a safe image URL for a Product.
    Priority: Product.primary_image().image -> p.image -> placeholder.
    """
    try:
        if hasattr(p, "primary_image"):
            pim = p.primary_image()
            if pim and getattr(pim, "image", None):
                url = getattr(pim.image, "url", "")
                if url:
                    return url
        # Fallback to direct field
        direct = getattr(p, "image", None)
        if direct:
            url = getattr(direct, "url", "")
            if url:
                return url
    except Exception:
        pass
    return static("img/product-placeholder.png")

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
    """Helper to check if a Django model has a specific field."""
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False

class ProductFilterMixin:
    """Consolidate product filtering and valuation logic."""
    def get_product_queryset(self, request, base_qs=None):
        if base_qs is None:
            base_qs = Product.objects.filter(is_deleted=False)
            
        qs = base_qs.select_related("business", "category", "uom", "bulk_uom").annotate(
            total_stock_value=ExpressionWrapper(
                Coalesce(F("purchase_price"), V(0)) * Coalesce(F("stock_qty"), V(0)),
                output_field=DecimalField(max_digits=18, decimal_places=2)
            )
        ).order_by("-id")

        q = request.GET.get("q")
        biz_id = request.GET.get("business")
        
        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(sku__icontains=q) |
                Q(barcode__icontains=q) |
                Q(category__name__icontains=q) |
                Q(business__name__icontains=q) |
                Q(company_name__icontains=q)
            )
        
        # Only apply global business filter if biz_id is present and we're not already filtered
        if biz_id and not hasattr(self, 'business'):
            qs = qs.filter(business_id=biz_id)
            
        # Price filter
        price_op = request.GET.get("price_op")
        price_val = request.GET.get("price_val")
        if price_op and price_val:
            try:
                price_decimal = Decimal(price_val)
                if price_op == "gte":
                    qs = qs.filter(sale_price__gte=price_decimal)
                elif price_op == "lte":
                    qs = qs.filter(sale_price__lte=price_decimal)
                elif price_op == "eq":
                    qs = qs.filter(sale_price=price_decimal)
            except (ValueError, InvalidOperation):
                pass
        
        # Stock filter
        stock_op = request.GET.get("stock_op")
        stock_val = request.GET.get("stock_val")
        if stock_op and stock_val:
            try:
                stock_decimal = Decimal(stock_val)
                if stock_op == "gte":
                    qs = qs.filter(stock_qty__gte=stock_decimal)
                elif stock_op == "lte":
                    qs = qs.filter(stock_qty__lte=stock_decimal)
                elif stock_op == "eq":
                    qs = qs.filter(stock_qty=stock_decimal)
            except (ValueError, InvalidOperation):
                pass
        
        return qs

    def get_grand_total_stock_value(self, qs):
        return qs.aggregate(total=Sum("total_stock_value"))["total"] or Decimal("0.00")
