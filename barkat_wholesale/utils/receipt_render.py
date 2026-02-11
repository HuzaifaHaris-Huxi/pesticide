from __future__ import annotations
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, List, Optional
import os
import sys
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont
from django.conf import settings

# Optional RTL (Urdu, Arabic) shaping support
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    _HAS_RTL = True
except ImportError:
    arabic_reshaper = None  # type: ignore
    get_display = None      # type: ignore
    _HAS_RTL = False

# ---- Style Configuration ----
TITLE_SIZE = 36
BODY_SIZE = 28
SMALL_SIZE = 22
LINE_H = int(BODY_SIZE * 1.5)
HEADER_GAP = int(BODY_SIZE * 0.8)
PAD = 20

# Column ratios for item table
ITEM_COL_RATIO = 0.42
QTY_COL_RATIO = 0.15
PRICE_COL_RATIO = 0.21
AMOUNT_COL_RATIO = 0.22

COL_GAP = 8
ROW_GAP = 8
SEP_WIDTH = 1
SEP_COLOR = (40, 40, 40)

# ---- Font Configuration ----
URDU_FONT_REGULAR = str(getattr(settings, "RECEIPT_URDU_FONT", "") or "")
URDU_FONT_BOLD = str(
    getattr(settings, "RECEIPT_URDU_FONT_BOLD", "") or URDU_FONT_REGULAR
)


def _load_font(path: str, size: int, font_type: str = "regular") -> ImageFont.ImageFont:
    """
    Load font with proper error handling and logging.
    Falls back to a working font if the specified one fails.
    """
    if not path:
        print(f"WARNING: No font path specified for {font_type} size {size}", file=sys.stderr)
        return ImageFont.load_default()
    
    if not os.path.exists(path):
        print(f"ERROR: Font file not found: {path}", file=sys.stderr)
        print(f"Please ensure the Urdu font is installed at: {path}", file=sys.stderr)
        return ImageFont.load_default()
    
    try:
        font = ImageFont.truetype(path, size=size)
        print(f"✓ Successfully loaded {font_type} font: {Path(path).name} (size {size})")
        return font
    except Exception as e:
        print(f"ERROR loading font {path}: {e}", file=sys.stderr)
        return ImageFont.load_default()


# Initialize fonts with logging
print("\n" + "="*60)
print("INITIALIZING FONTS")
print("="*60)
print(f"Regular font path: {URDU_FONT_REGULAR}")
print(f"Bold font path: {URDU_FONT_BOLD}")
print(f"RTL Support available: {_HAS_RTL}")
print("-"*60)

FONT_TITLE = _load_font(URDU_FONT_BOLD or URDU_FONT_REGULAR, TITLE_SIZE, "title")
FONT_BODY = _load_font(URDU_FONT_REGULAR, BODY_SIZE, "body")
FONT_SMALL = _load_font(URDU_FONT_REGULAR, SMALL_SIZE, "small")
FONT_BODY_BOLD = _load_font(URDU_FONT_BOLD or URDU_FONT_REGULAR, BODY_SIZE, "body-bold")
FONT_SMALL_BOLD = _load_font(URDU_FONT_BOLD or URDU_FONT_REGULAR, SMALL_SIZE, "small-bold")

print("="*60 + "\n")


# ---- RTL Text Handling ----
def _needs_rtl_shaping(text: str) -> bool:
    """Detect if text contains Arabic or Urdu characters."""
    if not text:
        return False
    for ch in text:
        code = ord(ch)
        if (
            0x0600 <= code <= 0x06FF or  # Arabic
            0x0750 <= code <= 0x077F or  # Arabic Supplement
            0x08A0 <= code <= 0x08FF or  # Arabic Extended-A
            0xFB50 <= code <= 0xFDFF or  # Arabic Presentation Forms-A
            0xFE70 <= code <= 0xFEFF     # Arabic Presentation Forms-B
        ):
            return True
    return False


def _shape_text(text: str) -> str:
    """
    Reshape Arabic/Urdu text for proper display.
    This joins disconnected letters and handles RTL direction.
    """
    if not text:
        return ""
    
    if not _HAS_RTL:
        if _needs_rtl_shaping(text):
            print(f"WARNING: Text contains Urdu/Arabic but RTL libraries not installed: {text[:30]}...", file=sys.stderr)
        return text
    
    if not _needs_rtl_shaping(text):
        return text
    
    try:
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    except Exception as e:
        print(f"ERROR shaping text: {e}", file=sys.stderr)
        return text


# ---- Helper Functions ----
def _money(v) -> str:
    """Format number as money with proper decimals."""
    try:
        q = Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        try:
            q = Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except Exception:
            return str(v)
    s = f"{q:,.2f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _qty2(v) -> str:
    """Format quantity with up to 2 decimal places."""
    try:
        q = Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        try:
            q = Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except Exception:
            try:
                q = Decimal(str(float(v))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            except Exception:
                return str(v)
    
    s = f"{q:f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _text_w(draw: ImageDraw.ImageDraw, txt: str, font: ImageFont.ImageFont) -> int:
    """Calculate text width with proper RTL shaping."""
    shaped = _shape_text(txt or "")
    try:
        bbox = draw.textbbox((0, 0), shaped, font=font)
        return int(bbox[2] - bbox[0])
    except Exception:
        try:
            return int(draw.textlength(shaped, font=font))
        except Exception:
            return len(txt) * 10  # Fallback estimation


def _draw_text(draw: ImageDraw.ImageDraw, xy, txt: str, font: ImageFont.ImageFont, fill="black"):
    """Draw text with proper RTL shaping."""
    shaped = _shape_text(txt or "")
    draw.text(xy, shaped, fill=fill, font=font)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> List[str]:
    """Wrap text to fit within max_w pixels."""
    words = (text or "").split()
    if not words:
        return [""]
    
    lines: List[str] = []
    cur: List[str] = []
    
    for w in words:
        trial = (" ".join(cur + [w])).strip()
        if _text_w(draw, trial, font) <= max_w:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
                cur = [w]
            else:
                # Word too long, break it
                buf = ""
                for ch in w:
                    trial_ch = buf + ch
                    if _text_w(draw, trial_ch, font) <= max_w:
                        buf = trial_ch
                    else:
                        if buf:
                            lines.append(buf)
                        buf = ch
                if buf:
                    cur = [buf]
    
    if cur:
        lines.append(" ".join(cur))
    
    return lines


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> str:
    """Truncate text with ellipsis if too long."""
    if _text_w(draw, text, font) <= max_w:
        return text
    
    ell = "…"
    if _text_w(draw, ell, font) > max_w:
        return ""
    
    lo, hi = 0, len(text)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        trial = text[:mid] + ell
        if _text_w(draw, trial, font) <= max_w:
            best = trial
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _draw_center(draw: ImageDraw.ImageDraw, x0: int, width: int, y: int, txt: str, font: ImageFont.ImageFont) -> int:
    """Draw centered text."""
    w = _text_w(draw, txt, font)
    _draw_text(draw, (x0 + (width - w) // 2, y), txt, font)
    return y + int(font.size * 1.4)


def _draw_divider(draw: ImageDraw.ImageDraw, x: int, y: int, width: int) -> int:
    """Draw a horizontal divider line."""
    draw.line((x, y, x + width, y), fill=SEP_COLOR, width=2)
    return y + int(BODY_SIZE * 0.6)


def _draw_kv_row(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    left_txt: str,
    right_txt: str,
    font: ImageFont.ImageFont,
    left_ratio: float = 0.55,
) -> int:
    """Draw a key-value row with left-aligned key and right-aligned value."""
    left_w = int(width * left_ratio)
    right_w = width - left_w
    
    left_lines = _wrap(draw, left_txt, font, left_w - 10)
    yy = y
    for line in left_lines:
        _draw_text(draw, (x, yy), line, font)
        yy += LINE_H
    
    if right_txt:
        rw = _text_w(draw, right_txt, font)
        rx = x + width - rw
        _draw_text(draw, (rx, y), right_txt, font)
    
    return max(yy, y + LINE_H)


# ---- Sales Order Receipt Renderer ----
def render_receipt_bitmap(
    *,
    business,
    order,
    items: Iterable,
    width_px: int = 576,
    out_dir: str = ".",
) -> str:
    """Render a sales order receipt with Urdu support."""
    pad = PAD
    x0 = pad
    content_w = width_px - (pad * 2)
    items = list(items)

    # Extract order data
    received_amount = Decimal(str(getattr(order, "received_amount", 0) or 0))
    receipt_method = (getattr(order, "receipt_method", "") or "cash").strip().lower()
    method_label = "Cash" if receipt_method != "bank" else "Bank"

    bank_label = ""
    bank = getattr(order, "bank_account", None)
    if bank and getattr(bank, "name", ""):
        label_bits = [str(getattr(bank, "bank_name", "") or getattr(bank, "name", "")).strip()]
        acc = getattr(bank, "account_number", "")
        if acc:
            label_bits.append(str(acc))
        bank_label = " / ".join([b for b in label_bits if b])

    # Calculate totals
    try:
        subtotal = sum(
            (Decimal(str(getattr(it, "quantity", 0))) * Decimal(str(getattr(it, "unit_price", 0))))
            for it in items
        )
    except Exception:
        subtotal = Decimal("0.00")

    tax_pct = Decimal(str(getattr(order, "tax_percent", 0) or 0))
    disc_pct = Decimal(str(getattr(order, "discount_percent", 0) or 0))
    tax_amt = (subtotal * tax_pct) / Decimal("100")
    disc_amt = (subtotal * disc_pct) / Decimal("100")
    net = subtotal + tax_amt - disc_amt

    paid_so_far = Decimal(str(getattr(order, "paid_so_far", 0) or 0))
    remaining_override = getattr(order, "remaining_amount", None)
    if remaining_override is not None:
        try:
            remaining = Decimal(str(remaining_override))
        except Exception:
            remaining = max(Decimal("0"), net - paid_so_far - received_amount)
    else:
        remaining = max(Decimal("0"), net - paid_so_far - received_amount)

    printed_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Balance calculations
    balance_amount = getattr(order, "balance_amount", None)
    balance_side = (getattr(order, "balance_side", "") or "").strip()

    prev_balance_amount = None
    prev_balance_side = ""
    final_balance_amount = None
    final_balance_side = ""

    if balance_amount is not None and balance_side in ("Dr", "Cr"):
        bal_amt = Decimal(str(balance_amount))
        sign_final = Decimal("1") if balance_side == "Dr" else Decimal("-1")
        signed_final = sign_final * bal_amt
        signed_prev = signed_final - net + received_amount

        if signed_prev == 0:
            prev_balance_amount = Decimal("0.00")
            prev_balance_side = ""
        else:
            prev_balance_amount = abs(signed_prev)
            prev_balance_side = "Dr" if signed_prev > 0 else "Cr"

        final_balance_amount = bal_amt
        final_balance_side = balance_side

    # Calculate required height
    dummy = Image.new("RGB", (width_px, 100), color=(255, 255, 255))
    d = ImageDraw.Draw(dummy)
    y = pad

    title = (
        getattr(business, "legal_name", None)
        or getattr(business, "name", None)
        or "Business"
    ).strip()

    y += int(TITLE_SIZE * 1.4)
    
    addr_lines = []
    if getattr(business, "address", ""):
        addr_lines.extend(_wrap(d, str(business.address).strip(), FONT_SMALL, content_w))
    
    contact_line = []
    if getattr(business, "phone", ""):
        contact_line.append(f"Phone: {business.phone}")
    if getattr(business, "email", ""):
        contact_line.append(str(business.email))
    if contact_line:
        addr_lines.append(" | ".join(contact_line))
    
    for _ in addr_lines:
        y += int(SMALL_SIZE * 1.3)
    y += HEADER_GAP

    y += LINE_H * 4  # Order info lines
    y += int(BODY_SIZE * 0.6) + 2 + int(BODY_SIZE * 0.6)
    y += LINE_H  # Header
    y += int(BODY_SIZE * 0.6) + 2 + int(BODY_SIZE * 0.6)

    for _ in items:
        y += LINE_H + ROW_GAP + 1

    y += int(BODY_SIZE * 0.6) + 2 + int(BODY_SIZE * 0.6)
    y += LINE_H * 4

    if prev_balance_amount is not None and prev_balance_side:
        y += LINE_H
    y += LINE_H
    if method_label == "Bank" and bank_label:
        y += LINE_H
    if final_balance_amount is not None and final_balance_side:
        y += LINE_H

    y += int(BODY_SIZE * 0.6) + 2 + int(BODY_SIZE * 0.6)
    y += int(SMALL_SIZE * 1.3) * 2

    total_h = y + pad

    # Create actual image
    img = Image.new("RGB", (width_px, total_h), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = pad

    # Draw header
    y = _draw_center(draw, x0, content_w, y, title, FONT_TITLE)
    for line in addr_lines:
        y = _draw_center(draw, x0, content_w, y, line, FONT_SMALL)
    y += HEADER_GAP

    # Order information
    _draw_text(draw, (x0, y), f"Order #{getattr(order, 'id', '')}", FONT_BODY_BOLD)
    y += LINE_H
    if getattr(order, "date", None):
        _draw_text(draw, (x0, y), f"Date: {order.date}", FONT_BODY)
        y += LINE_H
    if getattr(order, "customer_name", ""):
        _draw_text(draw, (x0, y), f"Customer: {order.customer_name}", FONT_BODY)
        y += LINE_H
    _draw_text(draw, (x0, y), f"Printed: {printed_at}", FONT_BODY)
    y += LINE_H

    y = _draw_divider(draw, x0, y, content_w)

    # Item table
    item_w = int(content_w * ITEM_COL_RATIO)
    qty_w = int(content_w * QTY_COL_RATIO)
    price_w = int(content_w * PRICE_COL_RATIO)
    amount_w = content_w - item_w - qty_w - price_w

    x_item = x0
    x_qty = x_item + item_w
    x_price = x_qty + qty_w
    x_amount = x_price + price_w
    x_end = x0 + content_w

    # Table header
    header_y = y
    _draw_text(draw, (x_item + COL_GAP, header_y), "Items", FONT_BODY_BOLD)
    _draw_text(draw, (x_qty + COL_GAP, header_y), "Qty", FONT_BODY_BOLD)
    _draw_text(draw, (x_price + COL_GAP, header_y), "Price", FONT_BODY_BOLD)
    amt_label = "Amount"
    amt_w = _text_w(draw, amt_label, FONT_BODY_BOLD)
    _draw_text(draw, (x_end - amt_w - COL_GAP, header_y), amt_label, FONT_BODY_BOLD)

    # Vertical separators
    draw.line((x_qty, header_y, x_qty, header_y + LINE_H - 4), fill=SEP_COLOR, width=SEP_WIDTH)
    draw.line((x_price, header_y, x_price, header_y + LINE_H - 4), fill=SEP_COLOR, width=SEP_WIDTH)
    draw.line((x_amount, header_y, x_amount, header_y + LINE_H - 4), fill=SEP_COLOR, width=SEP_WIDTH)

    y += LINE_H
    y = _draw_divider(draw, x0, y, content_w)

    # Item rows
    for it in items:
        name = getattr(getattr(it, "product", None), "name", None) or getattr(it, "product_name", "Item")
        qty = getattr(it, "quantity", 0) or 0
        rate = getattr(it, "unit_price", 0) or 0
        total = (Decimal(str(qty)) * Decimal(str(rate))) if (qty is not None and rate is not None) else Decimal("0")

        qty_str = _qty2(qty)
        price_str = _money(rate)
        total_str = _money(total)

        row_y = y

        item_max_w = item_w - COL_GAP * 2
        item_text = _ellipsize(draw, str(name), FONT_BODY, item_max_w)
        _draw_text(draw, (x_item + COL_GAP, row_y), item_text, FONT_BODY)

        _draw_text(draw, (x_qty + COL_GAP, row_y), qty_str, FONT_BODY)

        p_w = _text_w(draw, price_str, FONT_BODY)
        _draw_text(draw, (x_price + price_w - p_w - COL_GAP, row_y), price_str, FONT_BODY)

        t_w = _text_w(draw, total_str, FONT_BODY)
        _draw_text(draw, (x_end - t_w - COL_GAP, row_y), total_str, FONT_BODY)

        # Vertical separators
        draw.line((x_qty, row_y, x_qty, row_y + LINE_H - 4), fill=SEP_COLOR, width=SEP_WIDTH)
        draw.line((x_price, row_y, x_price, row_y + LINE_H - 4), fill=SEP_COLOR, width=SEP_WIDTH)
        draw.line((x_amount, row_y, x_amount, row_y + LINE_H - 4), fill=SEP_COLOR, width=SEP_WIDTH)

        line_y = row_y + LINE_H
        draw.line((x0, line_y, x0 + content_w, line_y), fill=SEP_COLOR, width=SEP_WIDTH)

        y += LINE_H + ROW_GAP + 1

    y = _draw_divider(draw, x0, y, content_w)

    # Totals
    y = _draw_kv_row(draw, x0, y, content_w, "SubTotal", _money(subtotal), FONT_BODY_BOLD)
    y = _draw_kv_row(draw, x0, y, content_w, f"Tax ({tax_pct}%)", _money(tax_amt), FONT_BODY)
    y = _draw_kv_row(draw, x0, y, content_w, f"Discount ({disc_pct}%)", _money(disc_amt), FONT_BODY)
    y = _draw_kv_row(draw, x0, y, content_w, "Net Total", _money(net), FONT_BODY_BOLD)

    if prev_balance_amount is not None and prev_balance_side:
        y = _draw_kv_row(
            draw, x0, y, content_w,
            "Total remaining",
            f"{_money(prev_balance_amount)} {prev_balance_side}",
            FONT_BODY_BOLD,
        )

    y = _draw_kv_row(
        draw, x0, y, content_w,
        "Received",
        f"{_money(received_amount)} ({method_label})",
        FONT_BODY_BOLD,
    )

    if method_label == "Bank" and bank_label:
        _draw_text(draw, (x0, y), f"Bank: {bank_label}", FONT_SMALL)
        y += LINE_H

    if final_balance_amount is not None and final_balance_side:
        y = _draw_kv_row(
            draw, x0, y, content_w,
            "Balance after this sale",
            f"{_money(final_balance_amount)} {final_balance_side}",
            FONT_BODY_BOLD,
        )

    y = _draw_divider(draw, x0, y, content_w)
    y = _draw_center(draw, x0, content_w, y, "Developed by Qonkar Technologies", FONT_SMALL)
    y = _draw_center(draw, x0, content_w, y, "Contact: 03058214945", FONT_SMALL)

    # Save image
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"receipt_order_{getattr(order, 'id', 'X')}.png"
    img.save(out_path)
    print(f"✓ Receipt saved: {out_path}")
    return str(out_path.resolve())


# ---- Quick Receipt Renderer ----
def render_quick_receipt_bitmap(
    *,
    business,
    payment,
    width_px: int = 576,
    out_dir: str = ".",
) -> str:
    """Render a quick payment receipt with Urdu support."""
    pad = PAD
    x0 = pad
    content_w = width_px - (pad * 2)

    printed_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    title = (
        getattr(business, "legal_name", None)
        or getattr(business, "name", None)
        or "Business"
    ).strip()

    dummy = Image.new("RGB", (width_px, 100), color=(255, 255, 255))
    d = ImageDraw.Draw(dummy)

    addr_lines = []
    if getattr(business, "address", ""):
        addr_lines.extend(
            _wrap(d, str(business.address).strip(), FONT_SMALL, content_w)
        )
    contact_bits = []
    if getattr(business, "phone", ""):
        contact_bits.append(f"Phone: {business.phone}")
    if getattr(business, "email", ""):
        contact_bits.append(str(business.email))
    if contact_bits:
        addr_lines.append(" | ".join(contact_bits))

    party_name = getattr(payment.party, "display_name", "") or ""
    amount = getattr(payment, "amount", Decimal("0")) or Decimal("0")
    received_now = getattr(payment, "received_amount", None)
    if received_now is None:
        received_now = amount

    method_label = (
        payment.get_payment_method_display()
        if hasattr(payment, "get_payment_method_display")
        else str(getattr(payment, "payment_method", "") or "")
    )
    ref_no = getattr(payment, "reference", "") or ""
    note = getattr(payment, "description", "") or ""
    date_val = getattr(payment, "date", None) or getattr(payment, "created_at", None)
    date_str = str(date_val) if date_val else ""

    balance_amount = getattr(payment, "balance_amount", None)
    balance_side = (getattr(payment, "balance_side", "") or "").strip()

    prev_text = None
    received_text = _money(received_now)
    closing_text = None

    if isinstance(balance_amount, Decimal):
        closing_abs = balance_amount
        closing_side = balance_side or ""

        if closing_side.upper() == "CR":
            closing_signed = -closing_abs
        else:
            closing_signed = closing_abs

        previous_signed = closing_signed + received_now

        if previous_signed >= 0:
            previous_side = "Dr"
            previous_abs = previous_signed
        else:
            previous_side = "Cr"
            previous_abs = -previous_signed

        prev_text = f"{_money(previous_abs)} {previous_side}"
        closing_text = f"{_money(closing_abs)} {closing_side}".strip()

    label_w = _text_w(d, "Reference: ", FONT_BODY)
    value_w = max(content_w - int(label_w) - 8, 40)

    party_lines = _wrap(d, party_name, FONT_BODY, value_w) if party_name else [""]
    ref_lines = _wrap(d, ref_no, FONT_BODY, value_w) if ref_no else []
    note_lines = _wrap(d, note, FONT_BODY, value_w) if note else []

    # Calculate height
    y = pad
    y += int(TITLE_SIZE * 1.4)
    for _ in addr_lines:
        y += int(SMALL_SIZE * 1.3)
    y += HEADER_GAP
    y += int(BODY_SIZE * 1.4)
    y += LINE_H * (2 + max(len(party_lines), 1) + 2)
    if ref_lines:
        y += LINE_H * len(ref_lines)
    if note_lines:
        y += LINE_H * len(note_lines)
    y += LINE_H + 4
    if prev_text is not None:
        y += LINE_H
    y += LINE_H
    if closing_text is not None:
        y += LINE_H
    y += LINE_H * 2

    total_h = y + pad

    # Create actual image
    img = Image.new("RGB", (width_px, total_h), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = pad

    # Header
    y = _draw_center(draw, x0, content_w, y, title, FONT_TITLE)
    for line in addr_lines:
        y = _draw_center(draw, x0, content_w, y, line, FONT_SMALL)
    y += HEADER_GAP

    y = _draw_center(draw, x0, content_w, y, "Receipt", FONT_BODY_BOLD)

    # Receipt details
    y = _draw_kv_row(draw, x0, y, content_w, "Date", date_str, FONT_BODY)

    if party_lines:
        y = _draw_kv_row(draw, x0, y, content_w, "Party", party_lines[0], FONT_BODY)
        for extra in party_lines[1:]:
            y = _draw_kv_row(draw, x0, y, content_w, "", extra, FONT_BODY)
    else:
        y = _draw_kv_row(draw, x0, y, content_w, "Party", "", FONT_BODY)

    y = _draw_kv_row(draw, x0, y, content_w, "Amount", _money(amount), FONT_BODY_BOLD)
    y = _draw_kv_row(draw, x0, y, content_w, "Method", method_label, FONT_BODY)

    if ref_lines:
        y = _draw_kv_row(draw, x0, y, content_w, "Reference", ref_lines[0], FONT_BODY)
        for extra in ref_lines[1:]:
            y = _draw_kv_row(draw, x0, y, content_w, "", extra, FONT_BODY)

    if note_lines:
        y = _draw_kv_row(draw, x0, y, content_w, "Note", note_lines[0], FONT_BODY)
        for extra in note_lines[1:]:
            y = _draw_kv_row(draw, x0, y, content_w, "", extra, FONT_BODY)

    y = _draw_kv_row(draw, x0, y, content_w, "Printed", printed_at, FONT_SMALL)

    y = _draw_divider(draw, x0, y, content_w)

    # Balance information
    if prev_text is not None:
        y = _draw_kv_row(
            draw, x0, y, content_w,
            "Previous remaining",
            prev_text,
            FONT_BODY,
        )

    y = _draw_kv_row(
        draw, x0, y, content_w,
        "Received now",
        received_text,
        FONT_BODY_BOLD,
    )

    if closing_text is not None:
        y = _draw_kv_row(
            draw, x0, y, content_w,
            "Balance after this receipt",
            closing_text,
            FONT_BODY_BOLD,
        )

    y = _draw_center(draw, x0, content_w, y, "Developed by Qonkar Technologies", FONT_SMALL)
    y = _draw_center(draw, x0, content_w, y, "Contact: 03058214945", FONT_SMALL)

    # Save image
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"quick_receipt_{getattr(payment, 'id', 'X')}.png"
    img.save(out_path)
    print(f"✓ Quick receipt saved: {out_path}")
    return str(out_path.resolve())