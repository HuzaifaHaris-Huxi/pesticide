# barkat/utils/barcode_label_render.py
"""
Generate barcode label images for printing.
38x28mm per label, 2 labels per row (2 columns).
Total media width: 80-82mm at 300 DPI.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from typing import List, Dict, Optional, Any

try:
    import qrcode
    from qrcode.image.pil import PilImage
except ImportError:
    qrcode = None
    PilImage = None

try:
    from barcode import Code128
    from barcode.writer import ImageWriter
    BARCODE_LIB_AVAILABLE = True
except ImportError:
    BARCODE_LIB_AVAILABLE = False

# Constants - 38x25-28mm labels at 203 DPI (thermal printer standard)
# Standard 2-up label roll specifications:
# - Individual Label: 38mm x 25-28mm
# - Horizontal Gap: 2mm between labels (CRITICAL for proper spacing)
# - Side Margins: typically ~1mm liner on each far edge
# - Vertical Gap: 3mm between rows (REQUIRED for gap sensor to detect)
#
# IMPORTANT: Use ROUNDING (not floor) for mm->px conversion.
# A 1-3px drift at 203DPI can be enough to push content into the physical gap,
# which shows up as "split" barcodes/text on 2-up media.
DPI = 203  # Standard DPI for thermal label printers (common alternatives: 180, 203, 300)
MM_TO_INCH = 1 / 25.4


def _mm_to_px(mm: float) -> int:
    return int(round(mm * MM_TO_INCH * DPI))


def _px_to_mm(px: float) -> float:
    return (float(px) / float(DPI)) * 25.4


# Label dimensions (per user requirements)
LABEL_WIDTH_MM = 38.0  # Each individual label width (1.5 inches = 38mm)
LABEL_HEIGHT_MM = 28.0  # Each individual label height (supports 25mm or 28mm, using 28mm)

# Media/Gap specifications (per user requirements)
HORIZONTAL_GAP_MM = 2.0  # Gap between the two labels in a row (CRITICAL: 2mm)
VERTICAL_GAP_MM = 3.0  # Gap between rows (REQUIRED: 3mm for gap sensor)
SIDE_MARGIN_MM = 1.0  # Most 80mm rolls have ~1mm liner on each far edge

# Internal label padding
LABEL_PADDING_MM = 1.5  # Internal padding within label

# Quiet zone for barcode scanning (CRITICAL: minimum 2mm on each side)
# Per user requirements: "Leave about 2mm of white space on the left and right of the barcode"
QUIET_ZONE_MM = 2.0  # Exactly 2mm quiet zone for barcode scanning

# Barcode sizing controls (tune for scan reliability)
# For 203 DPI thermal printers:
# - X-Dimension (narrowest bar) should be at least 10 mils (0.254mm) = ~2 pixels at 203 DPI
# - Recommended: 15 mils (0.381mm) = 3 pixels at 203 DPI for better scanning
# - Module width must align with printer pixels (integer multiples)
# - Minimum quiet zone: 10x X-dimension (typically 2.5-3mm minimum)
BARCODE_MODULE_WIDTH_MM = 0.38  # 15 mils = 3 pixels at 203 DPI (optimal for scanning)
# Height should be sufficient for scanner to read (minimum 6mm, recommended 8-10mm)
BARCODE_MODULE_HEIGHT_MM = 8.0  # bar height in mm (good balance of size and scannability)
MIN_BARCODE_MODULE_WIDTH_MM = 0.30  # Minimum 12 mils (0.30mm = ~2.4 pixels) - do not go below


def _render_code128_fitted(
    barcode_value: str,
    barcode_width_usable_px: int,
    available_height_px: int,
    debug: bool = False,
) -> Optional[Image.Image]:
    """
    Render a Code128 barcode that fits the requested pixel area WITHOUT resizing.

    Why: resizing distorts bar/module widths, which is the #1 cause of scan failures.
    We instead adjust module_width/module_height and re-render until it fits.
    
    CRITICAL for scanning:
    - Module width must be integer multiples of printer pixels (203 DPI = 0.125mm per pixel)
    - Minimum X-dimension: 0.254mm (10 mils) = ~2 pixels
    - Recommended: 0.381mm (15 mils) = 3 pixels for reliable scanning
    - Quiet zone handled separately (2mm minimum)
    """
    if not BARCODE_LIB_AVAILABLE:
        return None

    try:
        max_barcode_height_px = int(available_height_px * 0.6)
        target_height_mm = min(float(BARCODE_MODULE_HEIGHT_MM), _px_to_mm(max_barcode_height_px))

        # Start with optimal module width (15 mils = 3 pixels at 203 DPI)
        module_w = float(BARCODE_MODULE_WIDTH_MM)
        min_w = float(MIN_BARCODE_MODULE_WIDTH_MM)

        # Ensure module width aligns with printer pixels (203 DPI = 0.125mm per pixel)
        # Round to nearest pixel boundary for better scanning
        pixels_per_mm = DPI / 25.4
        module_w_pixels = module_w * pixels_per_mm
        # Round to nearest integer pixel for better alignment
        module_w_pixels = round(module_w_pixels)
        module_w = module_w_pixels / pixels_per_mm

        # Try a few widths, decreasing until it fits (but maintain pixel alignment)
        best_barcode = None
        for attempt in range(15):
            # Ensure module width is at least minimum and aligns with pixels
            if module_w < min_w:
                break
            
            # Re-align to pixels
            module_w_pixels = round(module_w * pixels_per_mm)
            if module_w_pixels < 2:  # Minimum 2 pixels
                break
            module_w = module_w_pixels / pixels_per_mm
            
            writer_options = {
                "module_width": module_w,
                "module_height": max(1.0, float(target_height_mm)),
                "quiet_zone": 0,  # we draw quiet zone ourselves
                "dpi": DPI,
                "write_text": False,
                "font_size": 0,
                "text_distance": 0,
                # Additional options for better quality
                "center_text": False,
                "background": "white",
                "foreground": "black",
            }

            code128 = Code128(barcode_value, writer=ImageWriter())
            barcode_img = code128.render(writer_options)
            # CRITICAL: Force 1-bit monochrome for sharp edges (no anti-aliasing)
            # This ensures bars are pure black/white, which scanners require
            barcode_img = barcode_img.convert("1", dither=Image.NONE)
            
            if barcode_img.mode != "RGB":
                barcode_img = barcode_img.convert("RGB")

            w, h = barcode_img.size
            if w <= barcode_width_usable_px and h <= max_barcode_height_px:
                if debug:
                    print(f"  ✓ Barcode rendered: {w}x{h}px, module_width={module_w:.3f}mm ({module_w_pixels:.1f}px)")
                return barcode_img
            
            # Store best attempt so far
            if best_barcode is None or (w <= barcode_width_usable_px * 1.1 and h <= max_barcode_height_px * 1.1):
                best_barcode = barcode_img

            # Too wide/tall: reduce module width by one pixel
            if module_w_pixels > 2:
                module_w_pixels -= 1
                module_w = module_w_pixels / pixels_per_mm
            else:
                break

        # Return best attempt if we have one, otherwise last render
        if best_barcode is not None:
            if debug:
                print(f"  ⚠️  Using best fit barcode (may be slightly oversized)")
            return best_barcode
        
        if debug:
            print(f"  ⚠️  Using last render attempt")
        return barcode_img
    except Exception as e:
        if debug:
            print(f"⚠️  Code128 render failed for '{barcode_value}': {e}")
        return None


# Derived layout (single source of truth)
BARCODES_PER_ROW = 2  # 2 columns per row
TOTAL_MEDIA_WIDTH_MM = (LABEL_WIDTH_MM * BARCODES_PER_ROW) + HORIZONTAL_GAP_MM + (SIDE_MARGIN_MM * 2)
TOTAL_LABELS_WIDTH_MM = (LABEL_WIDTH_MM * BARCODES_PER_ROW) + HORIZONTAL_GAP_MM

LABEL_WIDTH_PX = _mm_to_px(LABEL_WIDTH_MM)
LABEL_HEIGHT_PX = _mm_to_px(LABEL_HEIGHT_MM)
HORIZONTAL_GAP_PX = _mm_to_px(HORIZONTAL_GAP_MM)
VERTICAL_GAP_PX = _mm_to_px(VERTICAL_GAP_MM)
SIDE_MARGIN_PX = _mm_to_px(SIDE_MARGIN_MM)
LABEL_PADDING_PX = _mm_to_px(LABEL_PADDING_MM)
QUIET_ZONE_PX = _mm_to_px(QUIET_ZONE_MM)
TOTAL_MEDIA_WIDTH_PX = _mm_to_px(TOTAL_MEDIA_WIDTH_MM)
TOTAL_LABELS_WIDTH_PX = _mm_to_px(TOTAL_LABELS_WIDTH_MM)

# Starting X position for labels
START_X_PX = SIDE_MARGIN_PX


def render_barcode_labels(
    products: List[Dict],
    quantities: Dict[int, int],
    business_name: Optional[str] = None,
    out_dir: str = ".",
    debug: bool = False,
) -> str:
    """
    Render barcode labels for multiple products.
    Each label: Business Name, Product Name, Price (if available), Barcode
    Size: 38x28mm per label, 2 labels per row (2 columns).
    Total media width: 82mm at 203 DPI.
    
    Args:
        products: List of product dicts with keys: id, name, barcode, company_name (optional)
        quantities: Dict mapping product_id -> quantity of labels to print
        business_name: Business name to display on each label
        out_dir: Directory to save the image
        debug: Print debug info
    
    Returns:
        Path to generated PNG image
    """
    if debug:
        print("\n" + "="*60)
        print("RENDERING BARCODE LABELS")
        print("="*60)
        print(f"DPI: {DPI}")
        print(f"Total media width: {TOTAL_MEDIA_WIDTH_MM}mm = {TOTAL_MEDIA_WIDTH_PX}px")
        print(f"Label size: {LABEL_WIDTH_MM}x{LABEL_HEIGHT_MM}mm = {LABEL_WIDTH_PX}x{LABEL_HEIGHT_PX}px")
        print(f"Horizontal gap: {HORIZONTAL_GAP_MM}mm = {HORIZONTAL_GAP_PX}px")
        print(f"Vertical gap: {VERTICAL_GAP_MM}mm = {VERTICAL_GAP_PX}px (for gap sensor)")
        print(f"Side margins: {SIDE_MARGIN_MM:.1f}mm = {SIDE_MARGIN_PX}px each")
        print(f"Computed: 2*{LABEL_WIDTH_MM:.1f} + {HORIZONTAL_GAP_MM:.1f} + 2*{SIDE_MARGIN_MM:.1f} = {TOTAL_MEDIA_WIDTH_MM:.1f}mm")
        print(f"Label 1 start: {SIDE_MARGIN_MM:.1f}mm")
        print(f"Label 2 start: {SIDE_MARGIN_MM + LABEL_WIDTH_MM + HORIZONTAL_GAP_MM:.1f}mm")
        print(f"Business: {business_name or 'N/A'}")
        print(f"Products: {len(products)}")
        print(f"Quantities: {sum(quantities.values())} total labels")
    
    # Build flat list of all labels to print (in order) - NO DUPLICATION
    # Each product appears exactly 'quantity' times, sequentially
    label_list = []
    for product in products:
        product_id = product.get("id")
        if product_id not in quantities or quantities[product_id] <= 0:
            continue
        
        barcode_value = product.get("barcode", "")
        if not barcode_value:
            if debug:
                print(f"⚠️  Skipping product {product_id} (no barcode)")
            continue
        
        qty = quantities[product_id]
        # Add each label instance to the flat list - each prints ONCE
        for _ in range(qty):
            label_list.append(product)
    
    if not label_list:
        raise ValueError("No labels to generate")
    
    # Calculate total rows needed
    # Each row has exactly 2 labels (2 columns)
    total_labels = len(label_list)
    rows_needed = (total_labels + BARCODES_PER_ROW - 1) // BARCODES_PER_ROW
    
    # Calculate image dimensions
    # Image width = total media width (82mm)
    # Image height = (rows * label height) + ((rows - 1) * vertical gap)
    # Vertical gap is REQUIRED for gap sensor to detect new rows
    img_width = TOTAL_MEDIA_WIDTH_PX
    img_height = (rows_needed * LABEL_HEIGHT_PX) + ((rows_needed - 1) * VERTICAL_GAP_PX)
    
    if debug:
        print(f"\nImage dimensions:")
        print(f"  Total labels: {total_labels}")
        print(f"  Rows needed: {rows_needed}")
        print(f"  Image size: {img_width}x{img_height}px ({TOTAL_MEDIA_WIDTH_MM}mm x {img_height/DPI*25.4:.1f}mm)")
        print(f"  Labels per row: {BARCODES_PER_ROW} (2 columns)")
    
    # Create image at 203 DPI
    img = Image.new("RGB", (img_width, img_height), color=(255, 255, 255))
    
    # Set DPI metadata
    img.info['dpi'] = (DPI, DPI)
    
    draw = ImageDraw.Draw(img)

    # Optional visual guides to validate that the image "knows" it is 2-up media.
    # These guides are intentionally subtle and only drawn in debug mode.
    if debug:
        guide = (220, 220, 220)
        # Media edges
        draw.line([(0, 0), (0, img_height - 1)], fill=guide, width=1)
        draw.line([(img_width - 1, 0), (img_width - 1, img_height - 1)], fill=guide, width=1)
        # Column boundaries + gap boundaries for every row
        x0 = START_X_PX
        x1 = x0 + LABEL_WIDTH_PX
        x2 = x1 + HORIZONTAL_GAP_PX
        x3 = x2 + LABEL_WIDTH_PX
        for xx in (x0, x1, x2, x3):
            draw.line([(int(xx), 0), (int(xx), img_height - 1)], fill=guide, width=1)
    
    # Try to load fonts (fallback to default if not available)
    try:
        font_tiny = ImageFont.truetype("arial.ttf", int(8 * DPI / 96))
        font_small = ImageFont.truetype("arial.ttf", int(9 * DPI / 96))
        font_medium = ImageFont.truetype("arial.ttf", int(10 * DPI / 96))
        font_barcode = ImageFont.truetype("arial.ttf", int(8 * DPI / 96))
    except:
        # Fallback - scale default font
        font_tiny = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_barcode = ImageFont.load_default()
    
    if debug:
        print(f"\nRendering labels (sequential placement):")
    
    # Render each label in sequence (left to right, top to bottom)
    # CRITICAL: Each label prints ONCE, positioned sequentially
    # Row 0: Label 0 (left), Label 1 (right)
    # Row 1: Label 2 (left), Label 3 (right)
    # Row 2: Label 4 (left), Label 5 (right)
    # etc.
    for label_idx, product in enumerate(label_list):
        # Calculate row and column (0-based)
        # Row = label index divided by labels per row (2)
        # Column = label index modulo labels per row (0 or 1)
        row = label_idx // BARCODES_PER_ROW
        col = label_idx % BARCODES_PER_ROW
        
        # Calculate position
        # X: Start from side margin + (column * (label_width + horizontal_gap))
        x = START_X_PX + (col * (LABEL_WIDTH_PX + HORIZONTAL_GAP_PX))
        # Y: (row * (label_height + vertical_gap))
        # Vertical gap is REQUIRED between rows for gap sensor
        y = row * (LABEL_HEIGHT_PX + VERTICAL_GAP_PX)
        
        if debug and (label_idx < 10 or label_idx % 10 == 0):
            print(f"  Label {label_idx}: row={row}, col={col}, pos=({x:.1f}, {y:.1f})")
        
        product_name = product.get("name", "")
        barcode_value = product.get("barcode", "")
        
        # Draw label content
        current_y = y + LABEL_PADDING_PX
        label_center_x = x + (LABEL_WIDTH_PX / 2)
        label_width_usable = LABEL_WIDTH_PX - (LABEL_PADDING_PX * 2)
        
        # 1. Draw Business Name (top, center-aligned)
        if business_name:
            business_text = business_name[:25] + "..." if len(business_name) > 25 else business_name
            text_width = draw.textlength(business_text, font=font_tiny)
            text_x = label_center_x - (text_width / 2)
            draw.text(
                (text_x, current_y),
                business_text,
                fill=(0, 0, 0),
                font=font_tiny
            )
            current_y += int(10 * DPI / 96)  # Scaled spacing
        
        # 2. Draw Product Name (middle, center-aligned)
        product_lines = _wrap_text(draw, product_name, font_medium, label_width_usable, max_lines=2)
        if not product_lines:
            product_lines = [product_name[:18] + "..." if len(product_name) > 18 else product_name]
        
        line_height = int(12 * DPI / 96)
        for idx, line in enumerate(product_lines[:2]):
            text_width = draw.textlength(line, font=font_medium)
            text_x = label_center_x - (text_width / 2)
            draw.text(
                (text_x, current_y + (idx * line_height)),
                line,
                fill=(0, 0, 0),
                font=font_medium
            )
        
        current_y += len(product_lines) * line_height + int(3 * DPI / 96)

        # 2.5 Draw Price (optional, center-aligned)
        price_text = _get_price_text(product)
        if price_text:
            text_width = draw.textlength(price_text, font=font_small)
            text_x = label_center_x - (text_width / 2)
            draw.text(
                (text_x, current_y),
                price_text,
                fill=(0, 0, 0),
                font=font_small,
            )
            current_y += int(10 * DPI / 96)  # Scaled spacing
        
        # 3. Draw Barcode (bottom, with quiet zones, center-aligned)
        # CRITICAL: Quiet zones must be at least 2mm on left and right for scanning
        # For Code128, quiet zone should be 10x the X-dimension minimum
        # With X-dimension of 0.38mm, quiet zone should be ~3.8mm, but we use 2mm minimum
        label_bottom = y + LABEL_HEIGHT_PX
        available_height = label_bottom - current_y - LABEL_PADDING_PX
        
        barcode_start_y = current_y
        
        # Calculate barcode area with proper quiet zones
        # Usable width = label width - (2 * padding) - (2 * quiet zone)
        # This ensures at least 2mm white space on each side of the barcode
        # Quiet zone is critical for scanner to detect start/stop patterns
        barcode_width_usable = LABEL_WIDTH_PX - (LABEL_PADDING_PX * 2) - (QUIET_ZONE_PX * 2)
        
        # Ensure minimum usable width (at least 20mm for barcode)
        min_barcode_width_px = _mm_to_px(20.0)
        if barcode_width_usable < min_barcode_width_px:
            # Reduce padding if needed to ensure minimum barcode width
            barcode_width_usable = LABEL_WIDTH_PX - (QUIET_ZONE_PX * 2)
            barcode_area_left = x + QUIET_ZONE_PX
        else:
            # Center the barcode area horizontally within the label
            # Left edge of barcode area = label left + padding + quiet zone
            barcode_area_left = x + LABEL_PADDING_PX + QUIET_ZONE_PX
        
        barcode_area_right = barcode_area_left + barcode_width_usable
        
        # Use actual barcode library if available for scannable barcodes
        actual_barcode_height = 0
        if BARCODE_LIB_AVAILABLE:
            try:
                # Generate Code128 that FITS without resizing (future-proof scanning)
                barcode_img = _render_code128_fitted(
                    barcode_value=barcode_value,
                    barcode_width_usable_px=int(barcode_width_usable),
                    available_height_px=int(available_height),
                    debug=debug,
                )
                if barcode_img is None:
                    raise RuntimeError("Barcode render returned None")

                barcode_img_width, barcode_img_height = barcode_img.size

                # Center the barcode horizontally within the barcode area
                barcode_img_x = barcode_area_left + ((barcode_width_usable - barcode_img_width) // 2)
                
                # CRITICAL: Paste barcode using exact pixel coordinates (no interpolation)
                # Use Image.NEAREST resampling to preserve exact bar widths for scanning
                # This ensures bars align perfectly with printer pixels
                img.paste(barcode_img, (int(barcode_img_x), int(barcode_start_y)))
                actual_barcode_height = barcode_img_height
                
                if debug:
                    print(f"    Barcode placed at ({int(barcode_img_x)}, {int(barcode_start_y)}), size={barcode_img_width}x{barcode_img_height}px")
                    print(f"    Quiet zone: {QUIET_ZONE_MM}mm ({QUIET_ZONE_PX}px) on each side")
                
            except Exception as e:
                if debug:
                    print(f"⚠️  Failed to generate real barcode for '{barcode_value}', using pattern: {e}")
                # Fallback to pattern-based barcode
                raise RuntimeError(f"Failed to generate barcode: {e}")
        else:
            # Library not available? This should not happen if we check earlier.
            raise ImportError("python-barcode library not available. Please install it.")
        
        # Draw barcode number directly below barcode lines (minimal gap - 2px)
        barcode_text = barcode_value[:16] if len(barcode_value) > 16 else barcode_value
        text_width = draw.textlength(barcode_text, font=font_barcode)
        text_x = label_center_x - (text_width / 2)
        
        # Position text directly below barcode with minimal gap (2px)
        gap = 2
        barcode_text_y = barcode_start_y + max(0, int(actual_barcode_height)) + gap
            
        draw.text(
            (text_x, barcode_text_y),
            barcode_text,
            fill=(0, 0, 0),
            font=font_barcode
        )
    
    # Save image with 300 DPI
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    import hashlib
    hash_str = hashlib.md5(str(products).encode()).hexdigest()[:8]
    out_path = out_dir / f"barcode_labels_{hash_str}.png"
    
    # Save with DPI info and high quality settings
    # CRITICAL: Use PNG format with no compression to preserve exact pixel values
    # This ensures barcode bars are rendered exactly as intended for scanning
    img.save(out_path, dpi=(DPI, DPI), format='PNG', compress_level=0)
    
    if debug:
        print(f"\n✓ Barcode labels saved: {out_path}")
        print(f"  Image size: {img_width}x{img_height}px")
        print(f"  DPI: {DPI} (thermal printer standard)")
        print(f"  Label size: {LABEL_WIDTH_PX}x{LABEL_HEIGHT_PX}px ({LABEL_WIDTH_MM}x{LABEL_HEIGHT_MM}mm)")
        print(f"  Labels per row: {BARCODES_PER_ROW} (2 columns)")
        print(f"  Total labels: {total_labels}")
        print(f"  Total rows: {rows_needed}")
    
    return str(out_path.resolve())


def _wrap_text(draw, text, font, max_width, max_lines=2):
    """Wrap text to fit within max_width."""
    words = text.split()
    lines = []
    current_line = []
    current_width = 0
    
    for word in words:
        word_width = draw.textlength(word + " ", font=font)
        if current_width + word_width <= max_width:
            current_line.append(word)
            current_width += word_width
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
            current_width = word_width
            if len(lines) >= max_lines:
                break
    
    if current_line and len(lines) < max_lines:
        lines.append(" ".join(current_line))
    
    return lines[:max_lines]


def _get_price_text(product: Dict[str, Any]) -> Optional[str]:
    """
    Extract and format a price string from a product dict.

    Supports common keys across systems. Preference order is tuned so labels show the
    product's SALE/SELLING price first (if present).
    Returns None if no price is present/usable.
    """
    candidate_keys = (
        "sale_price",
        "selling_price",
        "price",
        "unit_price",
        "mrp",
        "retail_price",
    )

    value: Any = None
    for k in candidate_keys:
        if k in product and product.get(k) not in (None, ""):
            value = product.get(k)
            break

    if value in (None, ""):
        return None

    currency = product.get("currency_symbol") or "Rs "

    # Numeric types
    if isinstance(value, (int, float)):
        amount = float(value)
        if abs(amount - round(amount)) < 1e-9:
            return f"{currency}{int(round(amount))}"
        return f"{currency}{amount:.2f}"

    # Strings (try to parse, otherwise show as-is)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        normalized = (
            s.replace(",", "")
            .replace("PKR", "")
            .replace("Rs.", "")
            .replace("Rs", "")
            .strip()
        )
        try:
            amount = float(normalized)
            if abs(amount - round(amount)) < 1e-9:
                return f"{currency}{int(round(amount))}"
            return f"{currency}{amount:.2f}"
        except Exception:
            # If the value already includes currency/formatting, keep it.
            return s

    # Fallback for any other type
    return f"{currency}{value}"

