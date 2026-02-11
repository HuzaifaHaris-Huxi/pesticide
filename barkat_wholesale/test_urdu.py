import os
import django
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'barkat_wholesale.settings')
django.setup()

from PIL import Image, ImageDraw, ImageFont
from django.conf import settings

print("="*70)
print("DETAILED URDU RENDERING TEST")
print("="*70)

# Step 1: Check font path
font_path = str(settings.RECEIPT_URDU_FONT)
print(f"\n1. Font Configuration:")
print(f"   Path: {font_path}")
print(f"   Exists: {os.path.exists(font_path)}")

if not os.path.exists(font_path):
    print(f"   ERROR: Font file not found!")
    exit(1)

# Step 2: Load font
print(f"\n2. Loading Font...")
try:
    font_small = ImageFont.truetype(font_path, size=30)
    font_large = ImageFont.truetype(font_path, size=50)
    print(f"   ✓ Font loaded successfully")
except Exception as e:
    print(f"   ERROR: {e}")
    exit(1)

# Step 3: Check RTL libraries
print(f"\n3. RTL Libraries:")
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    print(f"   ✓ arabic_reshaper: Available")
    print(f"   ✓ bidi: Available")
    HAS_RTL = True
except ImportError as e:
    print(f"   ✗ RTL libraries missing: {e}")
    HAS_RTL = False

# Step 4: Create test image
print(f"\n4. Creating Test Image...")
img = Image.new("RGB", (800, 400), color=(255, 255, 255))
draw = ImageDraw.Draw(img)

# Draw border to confirm image is being created
draw.rectangle([(5, 5), (795, 395)], outline=(0, 0, 0), width=2)

y_position = 30

# Test 1: English text (should always work)
print(f"\n5. Test 1: English Text")
english_text = "English: Ahmad Ali"
try:
    draw.text((20, y_position), english_text, font=font_small, fill=(0, 0, 0))
    print(f"   ✓ Drew: {english_text}")
    y_position += 60
except Exception as e:
    print(f"   ✗ Error: {e}")

# Test 2: Urdu without reshaping
print(f"\n6. Test 2: Urdu Without Reshaping")
urdu_raw = "احمد علی"
try:
    draw.text((20, y_position), urdu_raw, font=font_small, fill=(255, 0, 0))
    print(f"   ✓ Drew raw Urdu: {urdu_raw}")
    print(f"   (This will likely show as boxes or disconnected)")
    y_position += 60
except Exception as e:
    print(f"   ✗ Error: {e}")

# Test 3: Urdu with reshaping (if libraries available)
if HAS_RTL:
    print(f"\n7. Test 3: Urdu WITH Reshaping")
    try:
        reshaped = arabic_reshaper.reshape(urdu_raw)
        bidi_text = get_display(reshaped)
        
        print(f"   Original: {urdu_raw}")
        print(f"   Reshaped: {reshaped}")
        print(f"   Bidi: {bidi_text}")
        
        draw.text((20, y_position), bidi_text, font=font_large, fill=(0, 128, 0))
        print(f"   ✓ Drew reshaped Urdu")
        y_position += 80
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
else:
    draw.text((20, y_position), "RTL libraries not installed", font=font_small, fill=(255, 0, 0))
    y_position += 60

# Test 4: More Urdu text
if HAS_RTL:
    print(f"\n8. Test 4: Additional Urdu Text")
    more_urdu = "یہ اردو ہے"
    try:
        reshaped2 = arabic_reshaper.reshape(more_urdu)
        bidi_text2 = get_display(reshaped2)
        draw.text((20, y_position), bidi_text2, font=font_small, fill=(0, 0, 255))
        print(f"   ✓ Drew: {more_urdu}")
        y_position += 60
    except Exception as e:
        print(f"   ✗ Error: {e}")

# Add labels
draw.text((20, y_position), "If you see this text, PIL is working", font=font_small, fill=(128, 128, 128))

# Step 5: Save image
output = Path("urdu_test_detailed.png")
try:
    img.save(output)
    print(f"\n" + "="*70)
    print(f"✓ Test image saved: {output.absolute()}")
    print(f"="*70)
    print(f"\nOpen the image and check:")
    print(f"1. Black border should be visible (confirms image creation)")
    print(f"2. English text should be readable")
    print(f"3. Urdu text should be connected (not boxes)")
    print(f"\nIf everything is blank:")
    print(f"   - The font might be corrupt")
    print(f"   - Try re-downloading MehrNastaliqWeb.ttf")
except Exception as e:
    print(f"\n✗ Error saving image: {e}")
    import traceback
    traceback.print_exc()