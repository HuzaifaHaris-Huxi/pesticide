# barkat/utils/pos_print.py
from pathlib import Path

try:
    import win32print
    import win32ui
    from PIL import Image, ImageWin
except Exception:
    win32print = None
    win32ui = None
    Image = None
    ImageWin = None

class PosPrintError(Exception):
    pass

def _require_windows_stack():
    if any(x is None for x in (win32print, win32ui, Image, ImageWin)):
        raise PosPrintError(
            "Windows printing stack not available. "
            "Install requirements and restart app: pip install pywin32 pillow"
        )

def raw_print_bitmap(printer_name: str, bmp_path: str, width_px: int = 576):
    _require_windows_stack()

    p = Path(bmp_path)
    if not p.exists():
        raise PosPrintError(f"Bitmap not found: {bmp_path}")

    # Open image and scale proportionally
    img = Image.open(p).convert("RGB")
    try:
        scale = width_px / max(img.width, 1)
        img = img.resize((int(width_px), int(img.height * scale)))
    except Exception as e:
        raise PosPrintError(f"Failed to scale image: {e}")

    # Open DC for the specific printer and do a GDI print job
    try:
        hDC = win32ui.CreateDC()
        hDC.CreatePrinterDC(printer_name)
    except Exception as e:
        raise PosPrintError(f"Cannot open printer '{printer_name}': {e}")

    try:
        # Start a GDI print document
        hDC.StartDoc("POS Receipt")
        hDC.StartPage()

        dib = ImageWin.Dib(img)
        # Paint at 0,0 in device units. For ESC/POS drivers that expose a GDI surface,
        # sending raw pixels at 1:1 often works. If needed, map to device DPI here.
        dib.draw(hDC.GetHandleOutput(), (0, 0, img.width, img.height))

        hDC.EndPage()
        hDC.EndDoc()
    except Exception as e:
        raise PosPrintError(f"Printing failed: {e}")
    finally:
        try:
            hDC.DeleteDC()
        except Exception:
            pass
        try:
            img.close()
        except Exception:
            pass
