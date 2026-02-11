import os
import urllib.request
from pathlib import Path

print("="*70)
print("DOWNLOADING NOTO SANS ARABIC (Guaranteed to work with PIL)")
print("="*70)

# Font directory
font_dir = Path(__file__).parent / "barkat" / "Fonts"
font_dir.mkdir(parents=True, exist_ok=True)

print(f"\nFont directory: {font_dir}")

# Download Noto Sans Arabic (this is NOT Nastaliq but WILL render)
font_url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansArabic/NotoSansArabic-Regular.ttf"
font_path = font_dir / "NotoSansArabic-Regular.ttf"

print(f"\nDownloading Noto Sans Arabic...")
print(f"Note: This is NOT traditional Nastaliq calligraphy")
print(f"But it WILL render Urdu text correctly in PIL")

try:
    req = urllib.request.Request(
        font_url,
        headers={'User-Agent': 'Mozilla/5.0'}
    )
    
    with urllib.request.urlopen(req) as response:
        font_data = response.read()
        
    with open(font_path, 'wb') as f:
        f.write(font_data)
    
    print(f"\n✓ Downloaded: {font_path}")
    print(f"✓ File size: {len(font_data)} bytes")
    
    # Test it immediately
    print("\n" + "="*70)
    print("TESTING THE FONT")
    print("="*70)
    
    from PIL import Image, ImageDraw, ImageFont
    import arabic_reshaper
    from bidi.algorithm import get_display
    
    test_font = ImageFont.truetype(str(font_path), size=40)
    test_img = Image.new("RGB", (600, 200), color=(255, 255, 255))
    test_draw = ImageDraw.Draw(test_img)
    
    # Draw border
    test_draw.rectangle([(5, 5), (595, 195)], outline=(255, 0, 0), width=3)
    
    # English
    test_draw.text((20, 20), "English: Ahmad Ali", font=test_font, fill=(0, 0, 0))
    
    # Urdu
    urdu = "احمد علی"
    reshaped = arabic_reshaper.reshape(urdu)
    bidi = get_display(reshaped)
    test_draw.text((20, 80), bidi, font=test_font, fill=(0, 128, 0))
    
    test_draw.text((20, 140), "Urdu text above should be visible", font=test_font, fill=(128, 128, 128))
    
    test_path = Path("noto_test.png")
    test_img.save(test_path)
    
    print(f"\n✓ Test image created: {test_path.absolute()}")
    print(f"\nOpen 'noto_test.png' to verify Urdu is rendering")
    
    print("\n" + "="*70)
    print("IF TEST IMAGE SHOWS URDU TEXT:")
    print("="*70)
    print("\nUpdate your settings.py:")
    print(f"\nRECEIPT_URDU_FONT = str(BASE_DIR / 'barkat' / 'Fonts' / 'NotoSansArabic-Regular.ttf')")
    print(f"RECEIPT_URDU_FONT_BOLD = RECEIPT_URDU_FONT")
    
except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()