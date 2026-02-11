from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic.edit import FormView
from django.utils import timezone  # <-- add this

from .forms import QuickReceiptForm
from .models import Payment, Business

from .utils.pos_print import raw_print_bitmap, PosPrintError
from .utils.receipt_render import render_quick_receipt_bitmap
from .ledger_views import (
    _compute_party_balance,
    _compute_opening_before_date_for_party,  # <-- add this
)
from datetime import datetime, date, date as _date, timedelta


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


class QuickReceiptCreateView(LoginRequiredMixin, FormView):
    template_name = "barkat/finance/quick_receipt.html"
    form_class = QuickReceiptForm
    success_url = reverse_lazy("quick_receipt_list")

    def get_context_data(self, **kwargs):
        """
        Add business tabs so user can pick which business will be used for printing.
        This does not change QuickReceiptForm.create_payment logic.
        """
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
        """
        Normal Save button, only save and redirect, no printing.
        """
        try:
            payment = form.create_payment(self.request.user)
        except Exception as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)



        messages.success(
            self.request,
            f"Receipt saved. {payment.party.display_name} gave {payment.amount} as {payment.get_payment_method_display()}.",
        )
        return super().form_valid(form)


class QuickReceiptUpdateView(LoginRequiredMixin, FormView):
    template_name = "barkat/finance/quick_receipt.html"
    form_class = QuickReceiptForm

    def dispatch(self, request, *args, **kwargs):
        # only allow editing incoming receipts
        self.payment = get_object_or_404(
            Payment,
            pk=kwargs.get("pk"),
            direction=Payment.IN,
        )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        businesses = Business.objects.filter(
            is_deleted=False,
            is_active=True,
        ).order_by("name", "id")

        biz = self.payment.business
        ctx["businesses"] = businesses
        ctx["business"] = biz
        ctx["payment"] = self.payment
        return ctx

    def get_initial(self):
        p = self.payment
        initial = {
            "party_id": p.party_id,
            "party_name": p.party.display_name if p.party_id else "",
            "amount": p.amount,
            "ref_no": p.reference,
            "note": p.description,
            "type": p.payment_method,  # "cash", "bank", "cheque"
        }

        if p.payment_method in (
            Payment.PaymentMethod.BANK,
            Payment.PaymentMethod.CHEQUE,
        ):
            initial["bank_account"] = p.bank_account_id

        if (
            p.payment_method == Payment.PaymentMethod.CHEQUE
            and hasattr(p, "cheque_status")
            and p.cheque_status
        ):
            initial["cheque_status"] = p.cheque_status

        return initial

    def form_valid(self, form):
        party = form.party
        method = form.cleaned_data["type"]
        amount = form.cleaned_data["amount"]
        bank_account = form.cleaned_data.get("bank_account")
        ref_no = form.cleaned_data.get("ref_no") or ""
        note = form.cleaned_data.get("note") or ""

        p = self.payment

        try:
            business = form._infer_business(self.request.user)
        except Exception as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

        p.business = business
        p.party = party
        p.amount = amount
        p.description = note
        p.reference = ref_no
        p.direction = Payment.IN

        if method == "cash":
            p.payment_method = Payment.PaymentMethod.CASH
            p.bank_account = None
            if hasattr(p, "cheque_status"):
                p.cheque_status = ""
        elif method == "bank":
            p.payment_method = Payment.PaymentMethod.BANK
            p.bank_account = bank_account
            if hasattr(p, "cheque_status"):
                p.cheque_status = ""
        else:
            p.payment_method = Payment.PaymentMethod.CHEQUE
            p.bank_account = bank_account
            if hasattr(p, "cheque_status"):
                selected_status = (
                    form.cleaned_data.get("cheque_status")
                    or Payment.ChequeStatus.PENDING
                )
                p.cheque_status = selected_status

        p.updated_by = self.request.user
        p.full_clean()
        p.save()



        messages.success(
            self.request,
            f"Receipt updated. {p.party.display_name} gave {p.amount} as {p.get_payment_method_display()}.",
        )
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("quick_receipt_list")


@method_decorator(csrf_exempt, name="dispatch")
class QuickReceiptPrintView(LoginRequiredMixin, View):
    """
    Save and print in one shot for quick receipt, called via AJAX from "Save and Print" button.
    If payment_id is provided in POST, update that existing payment and print.
    Otherwise create a new payment and print.
    """

    def post(self, request: HttpRequest, *args, **kwargs):
        try:
            form = QuickReceiptForm(request.POST or None)

            if not form.is_valid():
                return JsonResponse(
                    {
                        "ok": False,
                        "error": "Validation error",
                        "form_errors": form.errors,
                    },
                    status=400,
                )

            payment_id = request.POST.get("payment_id")

            if payment_id:
                # edit mode, update existing payment
                payment = get_object_or_404(
                    Payment,
                    pk=payment_id,
                    direction=Payment.IN,
                )

                party = form.party
                method = form.cleaned_data["type"]
                amount = form.cleaned_data["amount"]
                bank_account = form.cleaned_data.get("bank_account")
                ref_no = form.cleaned_data.get("ref_no") or ""
                note = form.cleaned_data.get("note") or ""

                try:
                    business = form._infer_business(request.user)
                except Exception as e:
                    return JsonResponse(
                        {"ok": False, "error": str(e)},
                        status=400,
                    )

                payment.business = business
                payment.party = party
                payment.amount = amount
                payment.description = note
                payment.reference = ref_no
                payment.direction = Payment.IN

                if method == "cash":
                    payment.payment_method = Payment.PaymentMethod.CASH
                    payment.bank_account = None
                    if hasattr(payment, "cheque_status"):
                        payment.cheque_status = ""
                elif method == "bank":
                    payment.payment_method = Payment.PaymentMethod.BANK
                    payment.bank_account = bank_account
                    if hasattr(payment, "cheque_status"):
                        payment.cheque_status = ""
                else:
                    payment.payment_method = Payment.PaymentMethod.CHEQUE
                    payment.bank_account = bank_account
                    if hasattr(payment, "cheque_status"):
                        selected_status = (
                            form.cleaned_data.get("cheque_status")
                            or Payment.ChequeStatus.PENDING
                        )
                        payment.cheque_status = selected_status

                payment.updated_by = request.user
                payment.full_clean()
                payment.save()

            else:
                # create and sync payment, original create behaviour
                payment = form.create_payment(request.user)



            # ---------- compute ledger style breakdown for printing ----------
            # For tx_date.
            #   opening = balance till tx_date - 1
            #   sales_today = debits on tx_date
            #   paid_today  = credits on tx_date
            #   total_remaining = opening + sales_today - paid_today
            party = payment.party
            balance_amount = None
            balance_side = ""
            opening_amount = Decimal("0.00")
            opening_side = ""
            sales_today = Decimal("0.00")
            paid_today = Decimal("0.00")

            if party and getattr(party, "id", None):
                raw_type = (getattr(party, "type", "") or "").upper()
                if "VENDOR" in raw_type or "SUPPLIER" in raw_type:
                    kind = "supplier"
                else:
                    kind = "customer"

                # Date of this payment, used as "today"
                tx_date = payment.date or timezone.localdate()

                # All active businesses, same as All businesses mode
                biz_list = list(
                    Business.objects.filter(
                        is_deleted=False,
                        is_active=True,
                    ).order_by("name", "id")
                )
                biz_ids = [b.id for b in biz_list]

                # 1. Totals up to previous day (opening)
                # _compute_opening_before_date_for_party computes totals up to prev_day = date_from - 1
                # so for prev_day = tx_date - 1 we pass date_from = tx_date
                prev_dr, prev_cr = _compute_opening_before_date_for_party(
                    kind=kind,
                    party_id=party.id,
                    biz_list=biz_list,
                    biz_ids=biz_ids,
                    date_from=tx_date,
                )

                # 2. Totals up to end of today
                # For target = tx_date we pass date_from = tx_date + 1
                end_dr, end_cr = _compute_opening_before_date_for_party(
                    kind=kind,
                    party_id=party.id,
                    biz_list=biz_list,
                    biz_ids=biz_ids,
                    date_from=tx_date + timedelta(days=1),
                )

                # Opening and closing raw balances, Dr minus Cr
                opening_raw = prev_dr - prev_cr
                closing_raw = end_dr - end_cr

                # Opening side and amount
                if opening_raw > 0:
                    opening_side = "Dr"
                    opening_amount = opening_raw
                elif opening_raw < 0:
                    opening_side = "Cr"
                    opening_amount = -opening_raw

                # Movements in this specific day
                delta_dr = end_dr - prev_dr
                delta_cr = end_cr - prev_cr

                # Do not show negative sales or paid figures
                if delta_dr < 0:
                    delta_dr = Decimal("0.00")
                if delta_cr < 0:
                    delta_cr = Decimal("0.00")

                # For customers debits are sales, credits are payments
                # For suppliers we keep same numeric breakdown, only label meaning differs
                sales_today = delta_dr
                paid_today = delta_cr

                # Closing balance after today
                if closing_raw >= 0:
                    balance_side = "Dr"
                    balance_amount = closing_raw
                else:
                    balance_side = "Cr"
                    balance_amount = -closing_raw

            # attach fields for renderer, no database fields added
            payment.balance_amount = balance_amount or Decimal("0.00")
            payment.balance_side = balance_side
            payment.received_amount = payment.amount

            # extra breakdown for printing only
            payment.opening_balance_amount = opening_amount
            payment.opening_balance_side = opening_side
            payment.sales_today = sales_today
            payment.paid_today = paid_today
            # total remaining based on formula: opening + sales - paid
            payment.total_remaining_amount = (
                (opening_amount if opening_side != "Cr" else -opening_amount)
                + sales_today
                - paid_today
            )

            # ---------- printing ----------
            business = payment.business
            if not business:
                bid = request.GET.get("business")
                if bid and bid.isdigit():
                    business = (
                        Business.objects
                        .filter(id=int(bid), is_deleted=False, is_active=True)
                        .first()
                    )
            if not business:
                business = (
                    Business.objects
                    .filter(is_deleted=False, is_active=True)
                    .order_by("name", "id")
                    .first()
                )
            if not business:
                return JsonResponse(
                    {"ok": False, "error": "No business found for printing."},
                    status=400,
                )

            width_px = _width_px_from_kind(request.GET.get("width_kind"))

            bmp_path = render_quick_receipt_bitmap(
                business=business,
                payment=payment,
                width_px=width_px,
                out_dir=TMP_DIR,
            )

            printer_name = _resolve_printer_name(business)
            raw_print_bitmap(
                printer_name=printer_name,
                bmp_path=bmp_path,
                width_px=width_px,
            )

            messages.success(
                request,
                "Receipt saved and printed successfully.",
            )

            return JsonResponse(
                {
                    "ok": True,
                    "path": str(bmp_path),
                    "printer": printer_name,
                    "payment_id": payment.id,
                    "balance_amount": str(balance_amount) if balance_amount is not None else None,
                    "balance_side": balance_side,
                }
            )

        except PosPrintError as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=400)
        except Exception as e:
            return JsonResponse({"ok": False, "error": f"Unexpected error: {e}"}, status=500)

