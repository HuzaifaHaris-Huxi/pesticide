from __future__ import annotations
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, List, Optional, Tuple
import os
import sys
from datetime import datetime, timedelta


from PIL import Image, ImageDraw, ImageFont
from django.conf import settings
from django.contrib.auth import get_user_model

# Optional RTL (Urdu, Arabic) shaping support
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    _HAS_RTL = True
    print("[OK] RTL libraries (arabic_reshaper, bidi) imported successfully")
except ImportError as e:
    arabic_reshaper = None  # type: ignore
    get_display = None      # type: ignore
    _HAS_RTL = False
    print(f"✗ RTL libraries not found: {e}")
    print("  Install with: pip install python-bidi arabic-reshaper")

# ---- Style Configuration ----
TITLE_SIZE = 40  # Increased for better readability
BODY_SIZE = 30   # Increased for better readability
SMALL_SIZE = 24  # Increased for better readability
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


class MultiScriptFontManager:
    """Manages fonts for multiple scripts with fallback support."""
    
    def __init__(self):
        # Configure font paths
        self.urdu_font_regular = URDU_FONT_REGULAR
        self.urdu_font_bold = URDU_FONT_BOLD or URDU_FONT_REGULAR
        
        # English/Latin font paths (common system fonts)
        self.english_font_paths = [
            # Linux
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
            # macOS
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/SFNSDisplay.ttf",
            # Windows
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/tahoma.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            # Cross-platform fallback
            "Arial.ttf",  # PIL will search system
            "DejaVuSans.ttf",
        ]
        
        # Try to find an English font
        self.english_font_path = None
        for font_path in self.english_font_paths:
            try:
                if os.path.exists(font_path):
                    # Test if font can be loaded
                    test_font = ImageFont.truetype(font_path, size=12)
                    self.english_font_path = font_path
                    print(f"[OK] Found English font: {Path(font_path).name}")
                    break
            except Exception:
                continue
        
        if not self.english_font_path:
            print("⚠ No specific English font found, will use default if needed")
        
        # Font cache
        self.font_cache = {}
    
    def _needs_urdu_font(self, text: str) -> bool:
        """Check if text needs Urdu/Arabic font."""
        return _needs_rtl_shaping(text)
    
    def _get_font_for_text(self, text: str, size: int, is_bold: bool = False) -> Tuple[ImageFont.ImageFont, bool]:
        """Return appropriate font for the text content."""
        if not text:
            # Default to Urdu font for empty text
            return self._load_font(self.urdu_font_bold if is_bold else self.urdu_font_regular, size), True
        
        # Check if text needs Urdu font
        needs_urdu = self._needs_urdu_font(text)
        
        # Check if text contains Latin characters that need proper rendering
        has_latin = False
        for ch in text:
            code = ord(ch)
            # Latin letters A-Z, a-z
            if (0x0041 <= code <= 0x005A) or (0x0061 <= code <= 0x007A):
                has_latin = True
                break
        
        # Choose font strategy
        if needs_urdu:
            # Text contains Urdu/Arabic - use Urdu font
            font_path = self.urdu_font_bold if is_bold else self.urdu_font_regular
            return self._load_font(font_path, size), True
        elif has_latin and self.english_font_path:
            # Text has Latin characters and we have an English font - use it
            return self._load_font(self.english_font_path, size), False
        else:
            # For numbers, symbols, or mixed - try English font first
            if self.english_font_path:
                return self._load_font(self.english_font_path, size), False
            else:
                # Default to Urdu font
                font_path = self.urdu_font_bold if is_bold else self.urdu_font_regular
                return self._load_font(font_path, size), False
    
    def _load_font(self, path: str, size: int) -> ImageFont.ImageFont:
        """Load font with caching."""
        if not path:
            return ImageFont.load_default()
        
        cache_key = f"{path}_{size}"
        
        if cache_key in self.font_cache:
            return self.font_cache[cache_key]
        
        try:
            if os.path.exists(path):
                font = ImageFont.truetype(path, size=size)
                self.font_cache[cache_key] = font
                return font
            else:
                # Try to load by filename (PIL searches system)
                font = ImageFont.truetype(Path(path).name, size=size)
                self.font_cache[cache_key] = font
                return font
        except Exception as e:
            print(f"⚠ Error loading font {path}: {e}")
            font = ImageFont.load_default()
            self.font_cache[cache_key] = font
            return font
    
    def get_font(self, size: int, font_type: str = "regular", text: Optional[str] = None) -> Tuple[ImageFont.ImageFont, bool]:
        """Get font with intelligent script detection."""
        is_bold = font_type in ("title", "body-bold", "small-bold", "bold")
        
        if text:
            return self._get_font_for_text(text, size, is_bold)
        else:
            # Default to Urdu font when no text provided
            font_path = self.urdu_font_bold if is_bold else self.urdu_font_regular
            return self._load_font(font_path, size), True

# Initialize font manager
font_manager = MultiScriptFontManager()


def _test_urdu_rendering(font_path: str) -> bool:
    """Test if the font can actually render Urdu characters."""
    if not os.path.exists(font_path):
        return False
    
    try:
        test_font = ImageFont.truetype(font_path, size=28)
        test_img = Image.new("RGB", (200, 100), color=(255, 255, 255))
        test_draw = ImageDraw.Draw(test_img)
        
        # Test Urdu text
        test_text = "احمد علی"
        
        # Try to get the bounding box
        bbox = test_draw.textbbox((10, 10), test_text, font=test_font)
        width = bbox[2] - bbox[0]
        
        # If width is too small or zero, font can't render Urdu
        if width < 5:
            print(f"✗ Font cannot render Urdu properly (width: {width}px)")
            return False
        
        print(f"[OK] Font can render Urdu (test width: {width}px)")
        return True
    except Exception as e:
        print(f"✗ Error testing font: {e}")
        return False


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
        print(f"[OK] Loaded {font_type} font: {Path(path).name} (size {size})")
        return font
    except Exception as e:
        print(f"ERROR loading font {path}: {e}", file=sys.stderr)
        return ImageFont.load_default()


# Initialize fonts with logging
print("\n" + "="*60)
print("INITIALIZING RECEIPT FONTS")
print("="*60)
print(f"Regular font path: {URDU_FONT_REGULAR}")
print(f"Bold font path: {URDU_FONT_BOLD}")
print(f"RTL Support available: {_HAS_RTL}")
print("-"*60)

# Test if font can render Urdu
if URDU_FONT_REGULAR:
    print("Testing Urdu rendering capability...")
    can_render = _test_urdu_rendering(URDU_FONT_REGULAR)
    if not can_render:
        print("⚠ WARNING: Font loaded but may not render Urdu correctly!")
        print("  Consider using: Jameel Noori Nastaleeq or Alvi Nastaleeq")

# Create basic font objects for compatibility (These will be used as references only)
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


def _shape_text(text: str, debug: bool = False) -> str:
    """
    Reshape Arabic/Urdu text for proper display.
    This joins disconnected letters and handles RTL direction.
    """
    if not text:
        return ""
    
    has_urdu = _needs_rtl_shaping(text)
    
    if debug and has_urdu:
        print(f"  Original: {text[:50]}")
        print(f"  Has Urdu: {has_urdu}")
        print(f"  RTL libs: {_HAS_RTL}")
    
    if not _HAS_RTL:
        if has_urdu:
            print(f"⚠ WARNING: Urdu text detected but RTL libraries not installed!")
            print(f"  Text: {text[:50]}")
            print(f"  Install: pip install python-bidi arabic-reshaper")
        return text
    
    if not has_urdu:
        return text
    
    try:
        reshaped = arabic_reshaper.reshape(text)
        result = get_display(reshaped)
        
        if debug:
            print(f"  Reshaped: {result[:50]}")
        
        return result
    except Exception as e:
        print(f"✗ Error shaping text: {e}", file=sys.stderr)
        print(f"  Text was: {text[:50]}")
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
    """Calculate text width with proper font selection."""
    # Get appropriate font for this text
    try:
        size = font.size
    except AttributeError:
        size = BODY_SIZE
    
    # Determine if bold
    is_bold = False
    font_str = str(font).lower()
    if "bold" in font_str or font == FONT_TITLE or font == FONT_BODY_BOLD or font == FONT_SMALL_BOLD:
        is_bold = True
    
    smart_font, is_rtl = font_manager._get_font_for_text(txt, size, is_bold)
    
    # Shape text if it's RTL
    if is_rtl:
        shaped = _shape_text(txt)
    else:
        shaped = txt
    
    try:
        bbox = draw.textbbox((0, 0), shaped, font=smart_font)
        return int(bbox[2] - bbox[0])
    except Exception:
        try:
            return int(draw.textlength(shaped, font=smart_font))
        except Exception:
            return len(txt) * 10  # Fallback estimation


def _draw_text(draw: ImageDraw.ImageDraw, xy, txt: str, font: ImageFont.ImageFont, fill="black", debug: bool = False):
    """Draw text with smart font selection based on content."""
    if not txt:
        return
    
    # Get font size
    try:
        size = font.size
    except AttributeError:
        size = BODY_SIZE
    
    # Determine if this should be bold based on font
    is_bold = False
    font_str = str(font).lower()
    if "bold" in font_str or font == FONT_TITLE or font == FONT_BODY_BOLD or font == FONT_SMALL_BOLD:
        is_bold = True
    
    # Get appropriate font for this text
    smart_font, is_rtl = font_manager._get_font_for_text(txt, size, is_bold)
    
    # Shape text if it's RTL
    if is_rtl:
        shaped = _shape_text(txt, debug=debug)
    else:
        shaped = txt
    
    if debug:
        print(f"  Drawing at {xy}: '{txt[:30]}...'")
        print(f"  Font: {'Bold' if is_bold else 'Regular'}, RTL: {is_rtl}")
        print(f"  Using font path: {getattr(smart_font, 'path', 'default')}")
    
    # Draw with smart font
    try:
        draw.text(xy, shaped, fill=fill, font=smart_font)
    except Exception as e:
        print(f"✗ Error drawing text '{txt[:20]}...': {e}")
        # Fallback to default font
        fallback_font = ImageFont.load_default()
        draw.text(xy, txt, fill=fill, font=fallback_font)



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
    debug: bool = False,
) -> int:
    """Draw a key-value row with left-aligned key and right-aligned value."""
    left_w = int(width * left_ratio)
    right_w = width - left_w
    
    left_lines = _wrap(draw, left_txt, font, left_w - 10)
    yy = y
    for line in left_lines:
        _draw_text(draw, (x, yy), line, font, debug=debug)
        yy += LINE_H
    
    if right_txt:
        rw = _text_w(draw, right_txt, font)
        rx = x + width - rw
        _draw_text(draw, (rx, y), right_txt, font, debug=debug)
    
    return max(yy, y + LINE_H)


# ---- Sales Order Receipt Renderer ----
# ---- Sales Order Receipt Renderer ----

def render_receipt_bitmap(
    *,
    business,
    order,
    items: Iterable,
    width_px: int = 576,
    out_dir: str = ".",
    debug: bool = False,
) -> str:
    """Render a sales order receipt with Urdu support."""
    
    if debug:
        print("\n" + "="*60)
        print("RENDERING ORDER RECEIPT")
        print("="*60)
    
    pad = PAD
    x0 = pad
    content_w = width_px - (pad * 2)
    items = list(items)

    # Extract order data
    # FIX: Get received amount. If the attribute is 0, check for payment applications
    received_amount = Decimal(str(getattr(order, "received_amount", 0) or 0))
    
    # If it still shows 0, try to calculate from the linked payments
    if received_amount == 0 and hasattr(order, 'receipt_applications'):
        try:
            received_amount = sum(app.amount for app in order.receipt_applications.all())
        except Exception:
            pass
    receipt_method = (getattr(order, "receipt_method", "") or "cash").strip().lower()
    if receipt_method == "bank":
        method_label = "Bank"
    elif receipt_method == "card":
        method_label = "Card"
    elif receipt_method == "on_credit":
        method_label = "On Credit"
    else:
        method_label = "Cash"

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

    # Get customer name with debug - FIXED: Ensure proper encoding
    customer_name = str(getattr(order, "customer_name", "") or "")
    if debug and customer_name:
        print(f"Customer name: '{customer_name}'")
        print(f"  Length: {len(customer_name)}")
        print(f"  Contains Urdu: {_needs_rtl_shaping(customer_name)}")
        # Print character codes for debugging
        for i, char in enumerate(customer_name[:20]):
            print(f"  Char {i}: '{char}' (U+{ord(char):04X})")

    # Get business name from UserSettings (first/consistent name)
    title = None
    subtitle = None  # Business model name (second/variable name)
    user = None
    if hasattr(order, 'created_by') and order.created_by:
        user = order.created_by
    elif hasattr(order, 'updated_by') and order.updated_by:
        user = order.updated_by
    
    if user:
        try:
            from barkat.models import UserSettings
            user_settings = getattr(user, 'settings', None)
            if user_settings and user_settings.business_name and user_settings.business_name.strip():
                title = user_settings.business_name.strip()
        except Exception:
            pass
    
    # Always get business model name as subtitle (second name that changes per business)
    subtitle = (
        getattr(business, "legal_name", None)
        or getattr(business, "name", None)
        or ""
    ).strip()
    
    # Fallback: if no UserSettings name, use business name as title
    if not title:
        title = subtitle or "Business"
        subtitle = None  # Don't show duplicate

    # Calculate required height
    dummy = Image.new("RGB", (width_px, 100), color=(255, 255, 255))
    d = ImageDraw.Draw(dummy)
    y = pad

    y += int(TITLE_SIZE * 1.4)
    
    # Add subtitle if business name is different from title
    if subtitle and subtitle != title:
        y += int(BODY_SIZE * 1.2)
    
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

    y += LINE_H * 6  # Order info lines (order number, item count, date, customer, printed)
    y += int(BODY_SIZE * 0.6) + 2 + int(BODY_SIZE * 0.6)
    y += LINE_H  # Header
    y += int(BODY_SIZE * 0.6) + 2 + int(BODY_SIZE * 0.6)

    # Each item takes 2 rows: product name, then qty and amount
    for _ in items:
        y += LINE_H * 2 + ROW_GAP + 1

    y += int(BODY_SIZE * 0.6) + 2 + int(BODY_SIZE * 0.6)
    y += LINE_H * 4

    if prev_balance_amount is not None and prev_balance_side:
        y += LINE_H
    y += LINE_H
    if method_label in ("Bank", "Card") and bank_label:
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

    # Draw header with reduced spacing
    y = _draw_center(draw, x0, content_w, y, title, FONT_TITLE)
    y += int(SMALL_SIZE * 0.5)  # Reduced gap after title
    
    # Draw subtitle (business model name) if different from title
    if subtitle and subtitle != title:
        y = _draw_center(draw, x0, content_w, y, subtitle, FONT_BODY)
        y += int(SMALL_SIZE * 0.3)
    
    for line in addr_lines:
        y = _draw_center(draw, x0, content_w, y, line, FONT_SMALL)
        y += int(SMALL_SIZE * 0.3)  # Reduced line spacing
    
    y += int(HEADER_GAP * 0.7)  # Reduced header gap

    # Order information - Show order number on top with larger font
    order_num = getattr(order, 'id', '')
    order_num_text = f"Sales Order #{order_num}"
    y = _draw_center(draw, x0, content_w, y, order_num_text, FONT_BODY_BOLD)
    y += LINE_H
    
    # Show number of items
    item_count = len(items)
    items_text = f"Items: {item_count}"
    y = _draw_center(draw, x0, content_w, y, items_text, FONT_BODY)
    y += LINE_H
    
    if getattr(order, "date", None):
        _draw_text(draw, (x0, y), f"Date: {order.date}", FONT_BODY)
        y += LINE_H
        
    if customer_name:
        if debug:
            print(f"\nDrawing customer name...")
            print(f"  Raw name: '{customer_name}'")
        
        # Special handling for customer name - draw label and value separately
        label = "Customer: "
        
        # Draw the label (English) with English font
        label_font, _ = font_manager._get_font_for_text(label, BODY_SIZE, False)
        draw.text((x0, y), label, fill="black", font=label_font)
        
        # Calculate position for customer name
        label_width = _text_w(draw, label, FONT_BODY)
        name_x = x0 + label_width
        
        # Draw the customer name with appropriate font
        if debug:
            print(f"  Label: '{label}' (width: {label_width})")
            print(f"  Name position: x={name_x}, y={y}")
        
        # Use smart font selection for the name only
        name_font, is_rtl = font_manager._get_font_for_text(customer_name, BODY_SIZE, False)
        
        # Shape the name if it's RTL
        if is_rtl:
            shaped_name = _shape_text(customer_name, debug=debug)
        else:
            shaped_name = customer_name
            
        if debug:
            print(f"  Using font: {name_font}")
            print(f"  Is RTL: {is_rtl}")
            print(f"  Shaped name: '{shaped_name[:50]}...'")
        
        draw.text((name_x, y), shaped_name, fill="black", font=name_font)
        y += LINE_H
    else:
        _draw_text(draw, (x0, y), "Customer: ", FONT_BODY)
        y += LINE_H
        
    _draw_text(draw, (x0, y), f"Printed: {printed_at}", FONT_BODY)
    y += LINE_H

    y = _draw_divider(draw, x0, y, content_w)

    # Item table - use full width for description
    # Layout: Description (full width), then Qty (center) and Amount (right) on next row; no price shown
    x_item = x0
    x_end = x0 + content_w

    # Table header - Description | Qty | Amount (no price)
    header_y = y
    _draw_text(draw, (x_item + COL_GAP, header_y), "Description", FONT_BODY_BOLD)
    
    # Center: "Qty" only
    qty_label = "Qty"
    qty_label_w = _text_w(draw, qty_label, FONT_BODY_BOLD)
    qty_label_x = x0 + (content_w - qty_label_w) // 2
    _draw_text(draw, (qty_label_x, header_y), qty_label, FONT_BODY_BOLD)
    
    # Right: "Amount"
    amt_label = "Amount"
    amt_w = _text_w(draw, amt_label, FONT_BODY_BOLD)
    _draw_text(draw, (x_end - amt_w - COL_GAP, header_y), amt_label, FONT_BODY_BOLD)

    y += LINE_H
    y = _draw_divider(draw, x0, y, content_w)

    # Item rows: product name on one row (full width), Qty (center) and Amount (right) on next row
    for it in items:
        name = getattr(getattr(it, "product", None), "name", None) or getattr(it, "product_name", "Item")
        qty = getattr(it, "quantity", 0) or 0
        rate = getattr(it, "unit_price", 0) or 0
        total = (Decimal(str(qty)) * Decimal(str(rate))) if (qty is not None and rate is not None) else Decimal("0")
        
        # Get unit information from item
        unit_code = ""
        if hasattr(it, "uom") and it.uom:
            unit_code = getattr(it.uom, "code", "") or ""
        elif hasattr(it, "product") and it.product:
            # Fallback to product's base unit
            product_uom = getattr(it.product, "uom", None)
            if product_uom:
                unit_code = getattr(product_uom, "code", "") or ""

        qty_str = _qty2(qty)
        total_str = _money(total)

        # Row 1: Product name (full width for description)
        row_y = y
        item_max_w = content_w - COL_GAP * 2
        item_text = _ellipsize(draw, str(name), FONT_BODY, item_max_w)
        _draw_text(draw, (x_item + COL_GAP, row_y), item_text, FONT_BODY)
        y += LINE_H

        # Row 2: Qty only (with unit if any) centered under "Qty" header, Amount on right
        row_y = y
        if unit_code:
            qty_display = f"{qty_str} {unit_code}"
        else:
            qty_display = qty_str
        qp_w = _text_w(draw, qty_display, FONT_BODY)
        qp_x = x0 + (content_w - qp_w) // 2
        _draw_text(draw, (qp_x, row_y), qty_display, FONT_BODY)
        
        # Amount on right
        amt_w = _text_w(draw, total_str, FONT_BODY)
        _draw_text(draw, (x_end - amt_w - COL_GAP, row_y), total_str, FONT_BODY)
        
        # Horizontal separator line
        line_y = row_y + LINE_H
        draw.line((x0, line_y, x0 + content_w, line_y), fill=SEP_COLOR, width=SEP_WIDTH)

        y += LINE_H + ROW_GAP + 1

    y = _draw_divider(draw, x0, y, content_w)

    # Totals - FIXED: Use bold font for balance information
    y = _draw_kv_row(draw, x0, y, content_w, "SubTotal", _money(subtotal), FONT_BODY)
    y = _draw_kv_row(draw, x0, y, content_w, f"Tax ({tax_pct}%)", _money(tax_amt), FONT_BODY)
    y = _draw_kv_row(draw, x0, y, content_w, f"Discount ({disc_pct}%)", _money(disc_amt), FONT_BODY)
    y = _draw_kv_row(draw, x0, y, content_w, "Net Total", _money(net), FONT_BODY_BOLD)

    if prev_balance_amount is not None and prev_balance_side:
        y = _draw_kv_row(
            draw, x0, y, content_w,
            "Previous Balance",
            f"{_money(prev_balance_amount)} {prev_balance_side}",
            FONT_BODY_BOLD,
        )

    y = _draw_kv_row(
        draw, x0, y, content_w,
        "Received",
        f"{_money(received_amount)} ({method_label})",
        FONT_BODY_BOLD,
    )

    if method_label in ("Bank", "Card") and bank_label:
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
    y = _draw_center(draw, x0, content_w, y, "Developed by QONKAR TECHNOLOGIES", FONT_SMALL)
    y = _draw_center(draw, x0, content_w, y, "Contact: 03058214945  |  www.qonkar.com", FONT_SMALL)

    # Save image
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"receipt_order_{getattr(order, 'id', 'X')}.png"
    img.save(out_path)
    
    if debug:
        print(f"[OK] Receipt saved: {out_path}")
        print("="*60 + "\n")
    
    return str(out_path.resolve())



# ---- Quick Receipt Renderer ----
def render_quick_receipt_bitmap(
    *,
    business,
    payment,
    width_px: int = 576,
    out_dir: str = ".",
    debug: bool = False,
) -> str:
    """Render a quick payment receipt with Urdu support."""
    
    if debug:
        print("\n" + "="*60)
        print("RENDERING QUICK RECEIPT")
        print("="*60)
    
    pad = PAD
    x0 = pad
    content_w = width_px - (pad * 2)

    printed_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Get business name from UserSettings (first/consistent name)
    title = None
    subtitle = None  # Business model name (second/variable name)
    user = None
    if hasattr(payment, 'created_by') and payment.created_by:
        user = payment.created_by
    elif hasattr(payment, 'updated_by') and payment.updated_by:
        user = payment.updated_by
    
    if user:
        try:
            from barkat.models import UserSettings
            user_settings = getattr(user, 'settings', None)
            if user_settings and user_settings.business_name and user_settings.business_name.strip():
                title = user_settings.business_name.strip()
        except Exception:
            pass
    
    # Always get business model name as subtitle (second name that changes per business)
    subtitle = (
        getattr(business, "legal_name", None)
        or getattr(business, "name", None)
        or ""
    ).strip()
    
    # Fallback: if no UserSettings name, use business name as title
    if not title:
        title = subtitle or "Business"
        subtitle = None  # Don't show duplicate

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
    
    if debug and party_name:
        print(f"Party name: '{party_name}'")
        print(f"  Contains Urdu: {_needs_rtl_shaping(party_name)}")
    
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

    # New data from QuickReceiptPrintView
    opening_amount = getattr(payment, "opening_balance_amount", None)
    opening_side = (getattr(payment, "opening_balance_side", "") or "").strip()
    sales_today = getattr(payment, "sales_today", None)
    paid_today = getattr(payment, "paid_today", None)

    balance_amount = getattr(payment, "balance_amount", None)
    balance_side = (getattr(payment, "balance_side", "") or "").strip()

    # Compute labels for dates
    tx_date = None
    if isinstance(date_val, datetime):
        tx_date = date_val.date()
    else:
        tx_date = date_val

    tx_date_str = ""
    opening_label = "Opening balance"
    if tx_date and hasattr(tx_date, "strftime"):
        tx_date_str = tx_date.strftime("%d-%m-%Y")
        yesterday = tx_date - timedelta(days=1)
        opening_label = f"Remaining till {yesterday.strftime('%d-%m-%Y')}"
    else:
        tx_date_str = date_str

    # Prepare texts for the summary section
    opening_text = None
    if isinstance(opening_amount, Decimal) and (opening_amount != 0 or opening_side):
        opening_text = f"{_money(opening_amount)} {opening_side}".strip()

    sales_text = None
    if isinstance(sales_today, Decimal) and sales_today != 0:
        sales_text = _money(sales_today)

    paid_text = None
    if isinstance(paid_today, Decimal) and paid_today != 0:
        paid_text = _money(paid_today)

    total_text = None
    if isinstance(balance_amount, Decimal):
        total_text = f"{_money(balance_amount)} {balance_side}".strip()

    received_text = _money(received_now)

    label_w = _text_w(d, "Reference: ", FONT_BODY)
    value_w = max(content_w - int(label_w) - 8, 40)

    party_lines = _wrap(d, party_name, FONT_BODY, value_w) if party_name else [""]
    ref_lines = _wrap(d, ref_no, FONT_BODY, value_w) if ref_no else []
    note_lines = _wrap(d, note, FONT_BODY, value_w) if note else []

    # Calculate height
    y = pad
    y += int(TITLE_SIZE * 1.4)
    
    # Add subtitle if business name is different from title
    if subtitle and subtitle != title:
        y += int(BODY_SIZE * 1.2)
    
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

    # Summary rows count
    summary_lines = 0
    if opening_text:
        summary_lines += 1
    if sales_text:
        summary_lines += 1
    if paid_text:
        summary_lines += 1
    if total_text:
        summary_lines += 1

    y += LINE_H * summary_lines
    y += LINE_H * 2  # footer lines

    total_h = y + pad

    # Create actual image
    img = Image.new("RGB", (width_px, total_h), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = pad

    # Header with reduced spacing
    y = _draw_center(draw, x0, content_w, y, title, FONT_TITLE)
    y += int(SMALL_SIZE * 0.5)
    
    # Draw subtitle (business model name) if different from title
    if subtitle and subtitle != title:
        y = _draw_center(draw, x0, content_w, y, subtitle, FONT_BODY)
        y += int(SMALL_SIZE * 0.3)
    
    for line in addr_lines:
        y = _draw_center(draw, x0, content_w, y, line, FONT_SMALL)
        y += int(SMALL_SIZE * 0.3)
    
    y += int(HEADER_GAP * 0.7)

    # Dynamic Title: "Receipt" for IN, "Payment Voucher" for OUT
    receipt_title = "Receipt"
    if getattr(payment, "is_voucher", False) or getattr(payment, "direction", "IN") == "OUT":
        receipt_title = "Payment Voucher"
        
    y = _draw_center(draw, x0, content_w, y, receipt_title, FONT_BODY_BOLD)

    # Receipt details
    y = _draw_kv_row(draw, x0, y, content_w, "Date", date_str, FONT_BODY)

    if party_lines:
        if debug:
            print("Drawing party name with smart font selection...")
        y = _draw_kv_row(draw, x0, y, content_w, "Party", party_lines[0], FONT_BODY, debug=debug)
        for extra in party_lines[1:]:
            y = _draw_kv_row(draw, x0, y, content_w, "", extra, FONT_BODY, debug=debug)
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

    # Ledger style summary
    if opening_text:
        y = _draw_kv_row(
            draw, x0, y, content_w,
            opening_label,
            opening_text,
            FONT_BODY_BOLD,
        )

    if sales_text:
        label = f"Sales on {tx_date_str}" if tx_date_str else "Sales today"
        y = _draw_kv_row(
            draw, x0, y, content_w,
            label,
            sales_text,
            FONT_BODY_BOLD,
        )

    if paid_text:
        label = f"Paid on {tx_date_str}" if tx_date_str else "Paid today"
        y = _draw_kv_row(
            draw, x0, y, content_w,
            label,
            paid_text,
            FONT_BODY_BOLD,
        )

    if total_text:
        y = _draw_kv_row(
            draw, x0, y, content_w,
            "Total remaining",
            total_text,
            FONT_BODY_BOLD,
        )

    # Footer
    y = _draw_center(draw, x0, content_w, y, "Developed by QONKAR TECHNOLOGIES", FONT_SMALL)
    y = _draw_center(draw, x0, content_w, y, "Contact: 03058214945  |  www.qonkar.com", FONT_SMALL)

    # Save image
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"quick_receipt_{getattr(payment, 'id', 'X')}.png"
    img.save(out_path)
    
    if debug:
        print(f"[OK] Quick receipt saved: {out_path}")
        print("="*60 + "\n")
    
    return str(out_path.resolve())


# ---- Diagnostic Test Function ----
def test_urdu_rendering():
    """
    Test function to verify Urdu rendering is working.
    Run this to diagnose issues.
    """
    print("\n" + "="*70)
    print("URDU RENDERING DIAGNOSTIC TEST")
    print("="*70)
    
    # Test 1: RTL libraries
    print("\n1. RTL Libraries:")
    print(f"   arabic_reshaper installed: {arabic_reshaper is not None}")
    print(f"   bidi installed: {get_display is not None}")
    print(f"   RTL support: {_HAS_RTL}")
    
    if not _HAS_RTL:
        print("   ✗ ISSUE: Install with: pip install python-bidi arabic-reshaper")
        return False
    
    # Test 2: Font file
    print("\n2. Font File:")
    print(f"   Path: {URDU_FONT_REGULAR}")
    if not URDU_FONT_REGULAR:
        print("   ✗ ISSUE: No font path configured in settings.py")
        return False
    
    if not os.path.exists(URDU_FONT_REGULAR):
        print(f"   ✗ ISSUE: Font file not found at: {URDU_FONT_REGULAR}")
        return False
    
    print("   [OK] Font file exists")
    
    # Test 3: Font loading
    print("\n3. Font Loading:")
    try:
        test_font = ImageFont.truetype(URDU_FONT_REGULAR, size=28)
        print("   [OK] Font loaded successfully")
    except Exception as e:
        print(f"   ✗ ISSUE: Cannot load font: {e}")
        return False
    
    # Test 4: Urdu rendering
    print("\n4. Urdu Rendering Test:")
    test_text = "احمد علی"
    print(f"   Test text: {test_text}")
    
    shaped = _shape_text(test_text, debug=True)
    print(f"   Shaped text: {shaped}")
    
    # Test 5: English rendering
    print("\n5. English Rendering Test:")
    test_english = "Ahmad Ali"
    print(f"   Test text: {test_english}")
    
    # Create test image
    print("\n6. Creating Test Image:")
    try:
        img = Image.new("RGB", (400, 150), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        
        # Draw Urdu text
        _draw_text(draw, (10, 10), test_text, FONT_BODY, debug=True)
        
        # Draw English text
        _draw_text(draw, (10, 50), test_english, FONT_BODY, debug=True)
        
        # Draw mixed text (customer name example)
        customer_name = "علی اکبر"  # This is from your receipt example
        _draw_text(draw, (10, 90), f"Customer: {customer_name}", FONT_BODY, debug=True)
        
        test_path = Path("customer_name_test.png")
        img.save(test_path)
        print(f"   [OK] Test image saved: {test_path.absolute()}")
        print(f"   Open this image to verify customer name rendering")
        
    except Exception as e:
        print(f"   ✗ ISSUE: Cannot create test image: {e}")
        return False
    
    print("\n" + "="*70)
    print("DIAGNOSTIC COMPLETE")
    print("="*70)
    
    return True