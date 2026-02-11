from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from datetime import datetime, date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic.edit import FormView
from django.views.generic import ListView, DeleteView
from django.db import transaction

from .forms import CashOutForm
from .models import Payment, Business, Party
from .utils.pos_print import raw_print_bitmap, PosPrintError
from .utils.receipt_render import render_quick_receipt_bitmap # We can reuse or adapt this
from .ledger_views import (
    _compute_party_balance,
    _compute_opening_before_date_for_party,
)

# use same tmp folder pattern as POS receipts
TMP_DIR: Path = Path(
    getattr(settings, "RECEIPT_TMP_DIR", Path(settings.BASE_DIR) / "tmp_receipts")
).resolve()
TMP_DIR.mkdir(parents=True, exist_ok=True)

def _width_px_from_kind(width_kind: str | None) -> int:
    wk = (width_kind or "80mm").strip().lower()
    return 576 if ("80" in wk or wk == "80mm") else 384

def _resolve_printer_name(business: Business) -> str:
    name = (business.pos_printer_name or "").strip()
    if not name:
        raise PosPrintError(
            "No POS printer is configured for this business. "
            "Open Business in admin and set 'pos_printer_name' to the exact Windows printer name."
        )
    return name

class CashOutListView(LoginRequiredMixin, ListView):
    model = Payment
    template_name = "barkat/finance/cash_out_list.html"
    context_object_name = "payments"
    paginate_by = 50

    def get_queryset(self):
        return Payment.objects.filter(
            direction=Payment.OUT,
            payment_method=Payment.PaymentMethod.CASH,
            is_deleted=False
        ).select_related('party', 'business').order_by('-date', '-created_at')

class CashOutCreateView(LoginRequiredMixin, FormView):
    template_name = "barkat/finance/cash_out.html"
    form_class = CashOutForm
    success_url = reverse_lazy("cash_out_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        businesses = Business.objects.filter(
            is_deleted=False,
            is_active=True,
        ).order_by("name", "id")

        biz = None
        bid = self.request.GET.get("business")
        if bid and bid.isdigit():
            biz = businesses.filter(id=int(bid)).first()

        ctx["businesses"] = businesses
        ctx["business"] = biz
        return ctx

    def form_valid(self, form):
        try:
            payment = form.create_payment(self.request.user)
        except Exception as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"Cash Out recorded. Paid Rs. {payment.amount} to {payment.party.display_name}.",
        )
        return super().form_valid(form)

class CashOutUpdateView(LoginRequiredMixin, FormView):
    template_name = "barkat/finance/cash_out.html"
    form_class = CashOutForm
    success_url = reverse_lazy("cash_out_list")

    def dispatch(self, request, *args, **kwargs):
        self.payment = get_object_or_404(
            Payment,
            pk=kwargs.get("pk"),
            direction=Payment.OUT,
            payment_method=Payment.PaymentMethod.CASH
        )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        businesses = Business.objects.filter(
            is_deleted=False,
            is_active=True,
        ).order_by("name", "id")

        ctx["businesses"] = businesses
        ctx["business"] = self.payment.business
        ctx["payment"] = self.payment
        return ctx

    def get_initial(self):
        p = self.payment
        return {
            "party_id": p.party_id,
            "party_name": p.party.display_name,
            "date": p.date,
            "amount": p.amount,
            "ref_no": p.reference,
            "note": p.description,
            "override_cash_limit": True, # Allow editing without re-checking limits if they just want to fix description/date
        }

    def form_valid(self, form):
        # We handle update manually here to reuse create_payment logic or just update
        p = self.payment
        try:
            p.party = form.party
            p.amount = form.cleaned_data["amount"]
            p.date = form.cleaned_data["date"]
            p.reference = form.cleaned_data.get("ref_no") or ""
            p.description = form.cleaned_data.get("note") or ""
            p.updated_by = self.request.user
            p.full_clean()
            p.save()
        except Exception as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"Cash Out updated for {p.party.display_name}.",
        )
        return super().form_valid(form)

@method_decorator(csrf_exempt, name="dispatch")
class CashOutPrintView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, *args, **kwargs):
        try:
            payment_id = request.POST.get("payment_id")
            if payment_id:
                payment = get_object_or_404(Payment, pk=payment_id, direction=Payment.OUT)
            else:
                form = CashOutForm(request.POST or None)
                if not form.is_valid():
                    return JsonResponse({"ok": False, "error": "Validation error", "form_errors": form.errors}, status=400)
                payment = form.create_payment(request.user)

            # Prepare for printing (Voucher Style)
            # We can use render_quick_receipt_bitmap but we might need a "Voucher" title
            # Let's add a temporary attribute to the payment object for the renderer
            payment.is_voucher = True 
            
            # Compute extra breakdown for printing
            party = payment.party
            balance_amount = Decimal("0.00")
            balance_side = ""
            
            if party:
                raw_type = (getattr(party, "type", "") or "").upper()
                kind = "supplier" if ("VENDOR" in raw_type or "SUPPLIER" in raw_type) else "customer"
                tx_date = payment.date or timezone.localdate()
                
                biz_list = list(Business.objects.filter(is_deleted=False, is_active=True).order_by("name", "id"))
                biz_ids = [b.id for b in biz_list]
                
                # Totals up to end of today
                end_dr, end_cr = _compute_opening_before_date_for_party(
                    kind=kind, party_id=party.id, biz_list=biz_list, biz_ids=biz_ids, date_from=tx_date + timedelta(days=1),
                )
                closing_raw = end_dr - end_cr
                if closing_raw >= 0:
                    balance_side = "Dr"
                    balance_amount = closing_raw
                else:
                    balance_side = "Cr"
                    balance_amount = -closing_raw

            payment.balance_amount = balance_amount
            payment.balance_side = balance_side
            
            business = payment.business
            width_px = _width_px_from_kind(request.GET.get("width_kind"))
            
            # Reuse existing renderer
            bmp_path = render_quick_receipt_bitmap(
                business=business,
                payment=payment,
                width_px=width_px,
                out_dir=TMP_DIR,
            )

            printer_name = _resolve_printer_name(business)
            raw_print_bitmap(printer_name=printer_name, bmp_path=bmp_path, width_px=width_px)

            return JsonResponse({
                "ok": True,
                "payment_id": payment.id,
                "balance_amount": str(balance_amount),
                "balance_side": balance_side,
            })

        except PosPrintError as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=400)
        except Exception as e:
            return JsonResponse({"ok": False, "error": f"Unexpected error: {e}"}, status=500)

class CashOutDeleteView(LoginRequiredMixin, View):
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        payment = get_object_or_404(
            Payment,
            pk=kwargs.get("pk"),
            direction=Payment.OUT,
            payment_method=Payment.PaymentMethod.CASH
        )
        party_name = payment.party.display_name
        payment.delete()
        messages.success(request, f"Cash Out for {party_name} deleted.")
        return redirect("cash_out_list")

    def get(self, request, *args, **kwargs):
        return self.post(request, *args, **kwargs)
