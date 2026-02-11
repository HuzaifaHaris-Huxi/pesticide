

# barkat/views/ledger_views.py
from __future__ import annotations
from urllib.parse import urlencode
import re
from django.db.models import Count, Sum
from django.db.models.functions import Coalesce
from datetime import datetime, date
from typing import Optional

from decimal import Decimal
from datetime import date as _date
from urllib.parse import urlencode
from django.db.models import Prefetch, Sum, F, Value, DecimalField, Q

from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views import View

from .models import Business, Party, Staff
from .ledger import build_ledger

from django.db.models import Q
import re
from django.db.models import Count, Sum
from django.db.models.functions import Coalesce
from datetime import datetime, date
from typing import Optional

from decimal import Decimal
from datetime import date as _date
from urllib.parse import urlencode
from django.db.models import Prefetch, Sum, F, Value, DecimalField, Q

from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views import View

from .models import Business, Party, Staff
from .ledger import build_ledger

from django.db.models import Qfrom urllib.parse import urlencode

from datetime import datetime, date
from typing import Optional

from decimal import Decimal
from datetime import date as _date
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views import View

from .models import Business, Party, Staff
from .ledger import build_ledger

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views import View

from .models import Business, Party, Staff
from .ledger import build_ledger


# ---- helpers ---------------------------------------------------------------

def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None




class LedgersListView(View):
    template = "barkat/finance/ledgers_list.html"
    partial_template = "barkat/finance/_ledgers_table.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        kind = (request.GET.get("kind") or "customer").strip().lower()
        if kind not in ("customer", "supplier", "staff"):
            kind = "customer"

        # business param can be an id or "all"
        business_param = (request.GET.get("business") or "").strip().lower()
        business = None
        if business_param.isdigit():
            business = get_object_or_404(Business, pk=int(business_param))
        # if it's "all" or missing, business stays None

        q = (request.GET.get("q") or "").strip()

        # Base queryset per tab
        if kind == "supplier":
            qs = Party.objects.filter(type__in=["VENDOR", "BOTH"])
        elif kind == "customer":
            qs = Party.objects.filter(type__in=["CUSTOMER", "BOTH"])
        else:
            qs = Staff.objects.all()

        # Search
        if q:
            if kind in ("supplier", "customer"):
                qs = qs.filter(
                    Q(display_name__icontains=q) |
                    Q(phone__icontains=q) |
                    Q(email__icontains=q)
                )
            else:
                qs = qs.filter(
                    Q(full_name__icontains=q) |
                    Q(phone__icontains=q) |
                    Q(cnic__icontains=q)
                )

        qs = qs.order_by("id")
        paginator = Paginator(qs, 10)
        page_obj = paginator.get_page(request.GET.get("page"))

        # ------- Balance column (current page only) -------------------------
        if kind in ("customer", "supplier"):
            if business is not None:
                # Single business balance
                for p in page_obj.object_list:
                    _rows, totals, _ = build_ledger(
                        kind=kind,
                        business_id=business.id,
                        entity_id=p.id,
                        date_from=None,
                        date_to=None,
                    )
                    p.bal_amount = totals.get("balance_abs")
                    p.bal_side = totals.get("balance_side")
            else:
                # All businesses: keep opening ONCE per party
                active_biz = list(
                    Business.objects.filter(is_deleted=False, is_active=True)
                    .order_by("name", "id")
                )
                for p in page_obj.object_list:
                    total_dr = Decimal("0.00")
                    total_cr = Decimal("0.00")
                    opening_kept = False

                    for b in active_biz:
                        rows_b, totals_b, _ = build_ledger(
                            kind=kind,
                            business_id=b.id,
                            entity_id=p.id,
                            date_from=None,
                            date_to=None,
                        )

                        # remove opening for subsequent businesses
                        cleaned_rows, ob_dr, ob_cr = _extract_opening(rows_b)

                        if opening_kept:
                            adj_dr = Decimal(totals_b.get("total_dr") or 0) - ob_dr
                            adj_cr = Decimal(totals_b.get("total_cr") or 0) - ob_cr
                        else:
                            adj_dr = Decimal(totals_b.get("total_dr") or 0)
                            adj_cr = Decimal(totals_b.get("total_cr") or 0)
                            if ob_dr > 0 or ob_cr > 0:
                                opening_kept = True

                        total_dr += adj_dr
                        total_cr += adj_cr

                    p.bal_amount = abs(total_dr - total_cr)
                    p.bal_side = "Dr" if total_dr >= total_cr else "Cr"

        else:
            # Staff: always compute in staff.business
            for s in page_obj.object_list:
                b = getattr(s, "business", None)
                if not b:
                    s.bal_amount = None
                    s.bal_side = None
                    continue
                _rows, totals, _ = build_ledger(
                    kind="staff",
                    business_id=b.id,
                    entity_id=s.id,
                    date_from=None,
                    date_to=None,
                )
                s.bal_amount = totals.get("balance_abs")
                s.bal_side = totals.get("balance_side")

        ctx = {
            "kind": kind,
            "business": business,  # None means "All"
            "businesses": Business.objects.order_by("name", "id"),
            "page_obj": page_obj,
            "q": q,
        }

        if request.headers.get("HX-Request") == "true":
            return render(request, self.partial_template, ctx)
        return render(request, self.template, ctx)


# ---- detail view -----------------------------------------------------------
# at top





_SO_PATTERNS = [
    r'\bSO\s*[-#]?\s*(\d+)\b',
    r'\bSALES?\s*ORDER\s*[-#]?\s*(\d+)\b',
]
_PO_PATTERNS = [
    r'\bPO\s*[-#]?\s*(\d+)\b',
    r'\bPURCHASE\s*ORDER\s*[-#]?\s*(\d+)\b',
]

# ---- helpers ---------------------------------------------------------------

def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

class LedgersListView(View):
    template = "barkat/finance/ledgers_list.html"
    partial_template = "barkat/finance/_ledgers_table.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        # Force customer-only
        kind = "customer"

        # business param can be an id or "all"
        business_param = (request.GET.get("business") or "").strip().lower()
        business = None
        if business_param.isdigit():
            business = get_object_or_404(Business, pk=int(business_param))

        q = (request.GET.get("q") or "").strip()

        # Only registered, not deleted, active customers
        qs = Party.objects.filter(
            type__in=["CUSTOMER", "BOTH"],
            is_deleted=False,
            is_active=True,
        )

        # Search
        if q:
            qs = qs.filter(
                Q(display_name__icontains=q) |
                Q(phone__icontains=q) |
                Q(email__icontains=q)
            )

        qs = qs.order_by("id")
        paginator = Paginator(qs, 10)
        page_obj = paginator.get_page(request.GET.get("page"))

        # ------- Balance column (current page only) -------------------------
        if business is not None:
            # Single business balance
            for p in page_obj.object_list:
                _rows, totals, _ = build_ledger(
                    kind="customer",
                    business_id=business.id,
                    entity_id=p.id,
                    date_from=None,
                    date_to=None,
                )
                p.bal_amount = totals.get("balance_abs")
                p.bal_side = totals.get("balance_side")
        else:
            # All businesses, keep opening once per party
            active_biz = list(
                Business.objects.filter(is_deleted=False, is_active=True)
                .order_by("name", "id")
            )
            for p in page_obj.object_list:
                total_dr = Decimal("0.00")
                total_cr = Decimal("0.00")
                opening_kept = False

                for b in active_biz:
                    rows_b, totals_b, _ = build_ledger(
                        kind="customer",
                        business_id=b.id,
                        entity_id=p.id,
                        date_from=None,
                        date_to=None,
                    )
                    cleaned_rows, ob_dr, ob_cr = _extract_opening(rows_b)

                    if opening_kept:
                        adj_dr = Decimal(totals_b.get("total_dr") or 0) - ob_dr
                        adj_cr = Decimal(totals_b.get("total_cr") or 0) - ob_cr
                    else:
                        adj_dr = Decimal(totals_b.get("total_dr") or 0)
                        adj_cr = Decimal(totals_b.get("total_cr") or 0)
                        if ob_dr > 0 or ob_cr > 0:
                            opening_kept = True

                    total_dr += adj_dr
                    total_cr += adj_cr

                p.bal_amount = abs(total_dr - total_cr)
                p.bal_side = "Dr" if total_dr >= total_cr else "Cr"

        ctx = {
            "kind": "customer",
            "business": business,  # None means All
            "businesses": Business.objects.order_by("name", "id"),
            "page_obj": page_obj,
            "q": q,
        }

        if request.headers.get("HX-Request") == "true":
            return render(request, self.partial_template, ctx)
        return render(request, self.template, ctx)

def _parse_date(s: Optional[str]) -> Optional[_date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _fmt(d: Optional[_date]) -> Optional[str]:
    return d.strftime("%Y-%m-%d") if d else None

def _looks_like_opening(ref: str | None, note: str | None) -> bool:
    """
    Heuristic to detect opening balance rows. Tweak tokens if your data differs.
    """
    r = (ref or "").strip().upper()
    n = (note or "").strip().upper()
    tokens = ("OPENING", "OPENING BALANCE", "OPEN BAL", "BALANCE B/F", "B/F")
    if r in tokens:
        return True
    if any(tok in r for tok in tokens):
        return True
    if any(tok in n for tok in tokens):
        return True
    return False

def _extract_opening(rows):
    """
    Split rows into (rows_wo_opening, opening_dr, opening_cr).
    Accepts a list of LedgerRow objects or dicts.
    """
    cleaned = []
    open_dr = Decimal("0.00")
    open_cr = Decimal("0.00")

    for r in rows:
        if isinstance(r, dict):
            ref = r.get("ref")
            note = r.get("note")
            dr = r.get("dr")
            cr = r.get("cr")
        else:
            ref = getattr(r, "ref", None)
            note = getattr(r, "note", None)
            dr = getattr(r, "dr", None)
            cr = getattr(r, "cr", None)

        if _looks_like_opening(ref, note):
            if dr:
                open_dr += Decimal(str(dr))
            if cr:
                open_cr += Decimal(str(cr))
        else:
            cleaned.append(r)

    return cleaned, open_dr, open_cr

def _rows_to_dicts(rows, extra: dict | None = None):
    """
    Normalize rows to dicts with keys: date, ref, note, dr, cr (+ extras).
    """
    out = []
    for r in rows:
        d = {
            "date": r.get("date") if isinstance(r, dict) else getattr(r, "date", None),
            "ref":  r.get("ref", "") if isinstance(r, dict) else getattr(r, "ref", "") or "",
            "note": r.get("note", "") if isinstance(r, dict) else getattr(r, "note", "") or "",
            "dr":   r.get("dr") if isinstance(r, dict) else getattr(r, "dr", None),
            "cr":   r.get("cr") if isinstance(r, dict) else getattr(r, "cr", None),
        }
        if extra:
            d.update(extra)
        out.append(d)
    return out

import re
from collections import defaultdict
from decimal import Decimal
from datetime import datetime, date as _date

from django.db.models import Sum, Count
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views import View
from django.db.models import Q

from .models import Business, Party, Staff
from .ledger import build_ledger

# If your SO/PO models live elsewhere, update these imports accordingly
from .models import SalesOrder, SalesOrderItem   # adjust path if needed
from .models import PurchaseOrder, PurchaseOrderItem  # adjust path if needed


# ------------- helpers to parse order ids and attach counts -----------------

# ------------- existing helpers you already have ----------------------------

def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _fmt(d):
    return d.strftime("%Y-%m-%d") if d else None

def _looks_like_opening(ref: str | None, note: str | None) -> bool:
    r = (ref or "").strip().upper()
    n = (note or "").strip().upper()
    tokens = ("OPENING", "OPENING BALANCE", "OPEN BAL", "BALANCE B/F", "B/F")
    if r in tokens:
        return True
    if any(tok in r for tok in tokens):
        return True
    if any(tok in n for tok in tokens):
        return True
    return False

def _extract_opening(rows):
    cleaned = []
    open_dr = Decimal("0.00")
    open_cr = Decimal("0.00")
    for r in rows:
        if isinstance(r, dict):
            ref = r.get("ref")
            note = r.get("note")
            dr = r.get("dr")
            cr = r.get("cr")
        else:
            ref = getattr(r, "ref", None)
            note = getattr(r, "note", None)
            dr = getattr(r, "dr", None)
            cr = getattr(r, "cr", None)
        if _looks_like_opening(ref, note):
            if dr:
                open_dr += Decimal(str(dr))
            if cr:
                open_cr += Decimal(str(cr))
        else:
            cleaned.append(r)
    return cleaned, open_dr, open_cr

def _rows_to_dicts(rows, extra: dict | None = None):
    out = []
    for r in rows:
        d = {
            "date": r.get("date") if isinstance(r, dict) else getattr(r, "date", None),
            "ref":  r.get("ref", "") if isinstance(r, dict) else getattr(r, "ref", "") or "",
            "note": r.get("note", "") if isinstance(r, dict) else getattr(r, "note", "") or "",
            "dr":   r.get("dr") if isinstance(r, dict) else getattr(r, "dr", None),
            "cr":   r.get("cr") if isinstance(r, dict) else getattr(r, "cr", None),
        }
        if extra:
            d.update(extra)
        out.append(d)
    return out

def _compute_running_balance(rows_dicts):
    running = Decimal("0.00")
    for d in rows_dicts:
        dr = Decimal(str(d["dr"])) if d.get("dr") not in (None, "", "-") else Decimal("0.00")
        cr = Decimal(str(d["cr"])) if d.get("cr") not in (None, "", "-") else Decimal("0.00")
        running = running + dr - cr
        d["run_amount"] = abs(running)
        d["run_side"] = "Dr" if running >= 0 else "Cr"


_SO_PATTERNS = (
    r"\bSO\s*#\s*(\d+)\b",
    r"\bSALES\s*ORDER\s*#?\s*(\d+)\b",
    r"\bS\.?O\.?\s*(\d+)\b",
)
_PO_PATTERNS = (
    r"\bPO\s*#\s*(\d+)\b",
    r"\bPURCHASE\s*ORDER\s*#?\s*(\d+)\b",
    r"\bP\.?O\.?\s*(\d+)\b",
)


# --- add near other helpers (imports) ---
import re
from django.db.models import Count



import re
from django.db.models import Sum

# Safe imports for orders
try:
    from .models import SalesOrder, SalesOrderItem  # adjust path if orders live elsewhere
except Exception:
    SalesOrder = None
    SalesOrderItem = None

try:
    from .models import PurchaseOrder, PurchaseOrderItem  # optional
except Exception:
    PurchaseOrder = None
    PurchaseOrderItem = None


_SO_REFS = [
    re.compile(r"\bSO\s*#\s*(\d+)\b", re.I),
    re.compile(r"\bSales\s*Order\s*#?\s*(\d+)\b", re.I),
]

_PO_REFS = [
    re.compile(r"\bPO\s*#\s*(\d+)\b", re.I),
    re.compile(r"\bPurchase\s*Order\s*#?\s*(\d+)\b", re.I),
]



class LedgersListView(View):
    template = "barkat/finance/ledgers_list.html"
    partial_template = "barkat/finance/_ledgers_table.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        kind = (request.GET.get("kind") or "customer").strip().lower()
        if kind not in ("customer", "supplier", "staff"):
            kind = "customer"

        # business param can be an id or "all"
        business_param = (request.GET.get("business") or "").strip().lower()
        business = None
        if business_param.isdigit():
            business = get_object_or_404(Business, pk=int(business_param))
        # if it's "all" or missing, business stays None

        q = (request.GET.get("q") or "").strip()

        # Base queryset per tab
        if kind == "supplier":
            qs = Party.objects.filter(type__in=["VENDOR", "BOTH"])
        elif kind == "customer":
            qs = Party.objects.filter(type__in=["CUSTOMER", "BOTH"])
        else:
            qs = Staff.objects.all()

        # Search
        if q:
            if kind in ("supplier", "customer"):
                qs = qs.filter(
                    Q(display_name__icontains=q) |
                    Q(phone__icontains=q) |
                    Q(email__icontains=q)
                )
            else:
                qs = qs.filter(
                    Q(full_name__icontains=q) |
                    Q(phone__icontains=q) |
                    Q(cnic__icontains=q)
                )

        qs = qs.order_by("id")
        paginator = Paginator(qs, 10)
        page_obj = paginator.get_page(request.GET.get("page"))

        # ------- Balance column (current page only) -------------------------
        if kind in ("customer", "supplier"):
            if business is not None:
                # Single business balance
                for p in page_obj.object_list:
                    _rows, totals, _ = build_ledger(
                        kind=kind,
                        business_id=business.id,
                        entity_id=p.id,
                        date_from=None,
                        date_to=None,
                    )
                    p.bal_amount = totals.get("balance_abs")
                    p.bal_side = totals.get("balance_side")
            else:
                # All businesses: keep opening ONCE per party
                active_biz = list(
                    Business.objects.filter(is_deleted=False, is_active=True)
                    .order_by("name", "id")
                )
                for p in page_obj.object_list:
                    total_dr = Decimal("0.00")
                    total_cr = Decimal("0.00")
                    opening_kept = False

                    for b in active_biz:
                        rows_b, totals_b, _ = build_ledger(
                            kind=kind,
                            business_id=b.id,
                            entity_id=p.id,
                            date_from=None,
                            date_to=None,
                        )

                        # remove opening for subsequent businesses
                        cleaned_rows, ob_dr, ob_cr = _extract_opening(rows_b)

                        if opening_kept:
                            adj_dr = Decimal(totals_b.get("total_dr") or 0) - ob_dr
                            adj_cr = Decimal(totals_b.get("total_cr") or 0) - ob_cr
                        else:
                            adj_dr = Decimal(totals_b.get("total_dr") or 0)
                            adj_cr = Decimal(totals_b.get("total_cr") or 0)
                            if ob_dr > 0 or ob_cr > 0:
                                opening_kept = True

                        total_dr += adj_dr
                        total_cr += adj_cr

                    p.bal_amount = abs(total_dr - total_cr)
                    p.bal_side = "Dr" if total_dr >= total_cr else "Cr"

        else:
            # Staff: always compute in staff.business
            for s in page_obj.object_list:
                b = getattr(s, "business", None)
                if not b:
                    s.bal_amount = None
                    s.bal_side = None
                    continue
                _rows, totals, _ = build_ledger(
                    kind="staff",
                    business_id=b.id,
                    entity_id=s.id,
                    date_from=None,
                    date_to=None,
                )
                s.bal_amount = totals.get("balance_abs")
                s.bal_side = totals.get("balance_side")

        ctx = {
            "kind": kind,
            "business": business,  # None means "All"
            "businesses": Business.objects.order_by("name", "id"),
            "page_obj": page_obj,
            "q": q,
        }

        if request.headers.get("HX-Request") == "true":
            return render(request, self.partial_template, ctx)
        return render(request, self.template, ctx)





_SO_REF_RE = re.compile(r"\bSO\s*#?\s*(\d+)\b", re.IGNORECASE)

def _parse_so_id_from_ref(ref: str | None) -> int | None:
    if not ref:
        return None
    m = _SO_REF_RE.search(ref)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


class LedgerDetailView(View):
    template = "barkat/finance/ledger_details.html"

    def get(self, request: HttpRequest, kind: str, entity_id: int) -> HttpResponse:
        kind = (kind or "").strip().lower()
        if kind not in ("customer", "supplier", "staff"):
            return redirect("/")

        date_from = _parse_date(request.GET.get("date_from"))
        date_to   = _parse_date(request.GET.get("date_to"))
        print_mode = request.GET.get("print") == "1"
        business_param = (request.GET.get("business") or "").strip().lower()
        all_mode = business_param == "all"

        def _ctx_common(extra: dict) -> dict:
            extra.update({
                "date_from": date_from,
                "date_to": date_to,
                "print_mode": print_mode,
                "businesses": Business.objects.filter(is_deleted=False, is_active=True).order_by("name", "id"),
                "all_mode": all_mode,
            })
            return extra

        # ---- Staff: always single business via staff.business --------------
        if kind == "staff":
            staff = get_object_or_404(Staff, pk=entity_id)
            business = staff.business

            url_bid = request.GET.get("business")
            if not url_bid or not url_bid.isdigit() or int(url_bid) != business.id:
                params = {"business": business.id}
                if date_from:  params["date_from"] = _fmt(date_from)
                if date_to:    params["date_to"]   = _fmt(date_to)
                if print_mode: params["print"]     = "1"
                return redirect(f"{request.path}?{urlencode(params)}")

            rows, totals, entity = build_ledger(
                kind="staff",
                business_id=business.id,
                entity_id=entity_id,
                date_from=date_from,
                date_to=date_to,
            )

            base_rows = _rows_to_dicts(rows)
            _compute_running_balance(base_rows)

            # No SO expansion for staff rows
            page_obj = None if print_mode else Paginator(base_rows, 25).get_page(request.GET.get("page"))

            return render(request, self.template, _ctx_common({
                "kind": kind,
                "business": business,
                "entity": entity,
                "rows_all": base_rows if print_mode else None,
                "page_obj": page_obj,
                "totals": totals,
                "show_business_switcher": False,
            }))

        # ---- Customer / Supplier -------------------------------------------
        party = get_object_or_404(Party, pk=entity_id)

        other_kind = None
        try:
            if party.type == Party.BOTH:
                other_kind = "supplier" if kind == "customer" else "customer"
        except Exception:
            pass

        # Utility to fetch Sales Orders + items for a given business set
        def _fetch_so_bundle(biz_ids: list[int] | None):
            """
            Returns dict: so_id -> {
                'net_total': Decimal,
                'paid_total': Decimal,
                'item_count': int,
                'items': [{'name', 'qty', 'unit_price', 'line_total'}],
            }
            Scopes to party (customer) + date_from/date_to + business ids.
            """
            if kind != "customer":
                return {}

            so_qs = SalesOrder.objects.filter(customer_id=party.id)
            if biz_ids:
                so_qs = so_qs.filter(business_id__in=biz_ids)

            if date_from:
                so_qs = so_qs.filter(created_at__date__gte=date_from)
            if date_to:
                so_qs = so_qs.filter(created_at__date__lte=date_to)

            so_qs = (
                so_qs.select_related("business")
                     .prefetch_related(
                         Prefetch(
                             "items",
                             queryset=SalesOrderItem.objects.select_related("product").order_by("id"),
                             to_attr="prefetched_items",
                         )
                     )
                     .order_by("-created_at", "-id")
            )

            bundle = {}
            for so in so_qs:
                items_list = []
                for it in getattr(so, "prefetched_items", []):
                    qty = it.quantity or Decimal("0")
                    rate = it.unit_price or Decimal("0")
                    items_list.append({
                        "name": getattr(it.product, "name", "—"),
                        "qty": qty,
                        "unit_price": rate,
                        "line_total": (qty * rate),
                    })
                bundle[so.id] = {
                    "net_total": so.net_total or Decimal("0.00"),
                    "paid_total": so.paid_total,  # property on model
                    "item_count": len(items_list),
                    "items": items_list,
                }
            return bundle

        # All businesses: keep opening once only
        if all_mode:
            biz_list = list(
                Business.objects.filter(is_deleted=False, is_active=True)
                .order_by("name", "id")
            )
            biz_ids = [b.id for b in biz_list]
            so_bundle = _fetch_so_bundle(biz_ids)

            all_rows = []
            total_dr = Decimal("0.00")
            total_cr = Decimal("0.00")

            opening_kept = False  # keep opening rows from the first business only

            for b in biz_list:
                rows_b, totals_b, _ = build_ledger(
                    kind=kind,
                    business_id=b.id,
                    entity_id=entity_id,
                    date_from=date_from,
                    date_to=date_to,
                )

                # Split out potential opening rows
                cleaned_rows, ob_dr, ob_cr = _extract_opening(rows_b)

                # If opening already kept, drop any further opening rows and adjust totals
                if opening_kept:
                    rows_for_merge = cleaned_rows
                    adj_total_dr = Decimal(totals_b.get("total_dr") or 0) - ob_dr
                    adj_total_cr = Decimal(totals_b.get("total_cr") or 0) - ob_cr
                else:
                    rows_for_merge = rows_b
                    adj_total_dr = Decimal(totals_b.get("total_dr") or 0)
                    adj_total_cr = Decimal(totals_b.get("total_cr") or 0)
                    if ob_dr > 0 or ob_cr > 0:
                        opening_kept = True

                # Normalize with business meta
                dict_rows = _rows_to_dicts(rows_for_merge, {"biz_id": b.id, "biz_name": b.name})

                # Attach SO markers (we'll expand after we compute running balance)
                for d in dict_rows:
                    so_id = _parse_so_id_from_ref(d.get("ref"))
                    if so_id and so_id in so_bundle:
                        d["so_id"] = so_id
                        d["so_item_count"] = so_bundle[so_id]["item_count"]
                        d["so_paid_total"] = so_bundle[so_id]["paid_total"]
                        d["so_net_total"] = so_bundle[so_id]["net_total"]
                        d["_so_items"] = so_bundle[so_id]["items"]  # internal key for expansion
                all_rows.extend(dict_rows)

                total_dr += adj_total_dr
                total_cr += adj_total_cr

            # Sort combined and compute running balance
            all_rows.sort(key=lambda x: ((x["date"] or _date.min), str(x["ref"] or "")))
            _compute_running_balance(all_rows)

            # Expand rows by injecting item-detail lines AFTER each SO row (non-posting)
            expanded_rows = []
            for d in all_rows:
                expanded_rows.append(d)
                if d.get("so_id") and d.get("_so_items"):
                    for it in d["_so_items"]:
                        expanded_rows.append({
                            "date": "",  # decorative
                            "ref": f"• {it['name']}",
                            "note": f"Qty {it['qty']} × {it['unit_price']} = {it['line_total']}",
                            "dr": None,
                            "cr": None,
                            # copy running balance of parent so it stays visually stable
                            "run_amount": d.get("run_amount"),
                            "run_side": d.get("run_side"),
                            # show biz chip in All mode
                            "biz_id": d.get("biz_id"),
                            "biz_name": d.get("biz_name"),
                            # flags for template
                            "is_item_row": True,
                        })

            totals = {
                "total_dr": total_dr,
                "total_cr": total_cr,
                "balance_abs": abs(total_dr - total_cr),
                "balance_side": "Dr" if total_dr >= total_cr else "Cr",
            }

            page_obj = None if print_mode else Paginator(expanded_rows, 25).get_page(request.GET.get("page"))

            return render(request, self.template, _ctx_common({
                "kind": kind,
                "business": None,   # All
                "entity": party,
                "rows_all": expanded_rows if print_mode else None,
                "page_obj": page_obj,
                "totals": totals,
                "show_business_switcher": True,
                "other_kind": other_kind,
            }))

        # ---------------- Single business ----------------
        business_id = request.GET.get("business")
        if not business_id or not business_id.isdigit():
            inferred = getattr(party, "default_business", None)
            target_biz = inferred or Business.objects.order_by("name", "id").first()
            if not target_biz:
                return HttpResponse("No Business found. Please create a Business first.", status=400)
            params = {"business": target_biz.id}
            if date_from:  params["date_from"] = _fmt(date_from)
            if date_to:    params["date_to"]   = _fmt(date_to)
            if print_mode: params["print"]     = "1"
            return redirect(f"{request.path}?{urlencode(params)}")

        business = get_object_or_404(Business, pk=int(business_id))

        # Build ledger base rows
        rows, totals, _entity = build_ledger(
            kind=kind,
            business_id=business.id,
            entity_id=entity_id,
            date_from=date_from,
            date_to=date_to,
        )

        base_rows = _rows_to_dicts(rows)

        # Fetch SO bundle for this single business (only for customers)
        so_bundle = _fetch_so_bundle([business.id])

        # Tag possible SO rows
        for d in base_rows:
            so_id = _parse_so_id_from_ref(d.get("ref"))
            if so_id and so_id in so_bundle:
                d["so_id"] = so_id
                d["so_item_count"] = so_bundle[so_id]["item_count"]
                d["so_paid_total"] = so_bundle[so_id]["paid_total"]
                d["so_net_total"] = so_bundle[so_id]["net_total"]
                d["_so_items"] = so_bundle[so_id]["items"]

        # Compute running balance on base rows first
        _compute_running_balance(base_rows)

        # Expand rows by injecting item-detail lines AFTER each SO row (non-posting)
        expanded_rows = []
        for d in base_rows:
            expanded_rows.append(d)
            if d.get("so_id") and d.get("_so_items"):
                for it in d["_so_items"]:
                    expanded_rows.append({
                        "date": "",
                        "ref": f"• {it['name']}",
                        "note": f"Qty {it['qty']} × {it['unit_price']} = {it['line_total']}",
                        "dr": None,
                        "cr": None,
                        "run_amount": d.get("run_amount"),
                        "run_side": d.get("run_side"),
                        "is_item_row": True,
                    })

        page_obj = None if print_mode else Paginator(expanded_rows, 25).get_page(request.GET.get("page"))

        return render(request, self.template, _ctx_common({
            "kind": kind,
            "business": business,
            "entity": party,
            "rows_all": expanded_rows if print_mode else None,
            "page_obj": page_obj,
            "totals": totals,
            "show_business_switcher": True,
            "other_kind": other_kind,
        }))




