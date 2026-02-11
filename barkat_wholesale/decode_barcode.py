"""
Enhanced barcode decoder with image preprocessing and multiple attempts.
"""
from pathlib import Path
from PIL import Image, ImageEnhance, ImageOps
import sys

try:
    from pyzbar.pyzbar import decode
    PYZBAR_AVAILABLE = True
except ImportError:
    PYZBAR_AVAILABLE = False

def preprocess_image(img):
    """Apply various preprocessing techniques to improve barcode readability."""
    processed_images = []
    
    # Original
    processed_images.append(("Original", img))
    
    # Convert to RGB if RGBA
    if img.mode == 'RGBA':
        rgb_img = Image.new('RGB', img.size, (255, 255, 255))
        rgb_img.paste(img, mask=img.split()[3])
        img = rgb_img
        processed_images.append(("RGB Conversion", img))
    
    # Convert to grayscale
    gray = img.convert('L')
    processed_images.append(("Grayscale", gray))
    
    # Increase contrast
    enhancer = ImageEnhance.Contrast(gray)
    high_contrast = enhancer.enhance(2.0)
    processed_images.append(("High Contrast", high_contrast))
    
    # Binary threshold
    threshold = 128
    binary = gray.point(lambda x: 0 if x < threshold else 255, '1')
    processed_images.append(("Binary Threshold", binary))
    
    # Invert (in case it's a negative)
    inverted = ImageOps.invert(gray)
    processed_images.append(("Inverted", inverted))
    
    # Scale up 2x
    larger = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    processed_images.append(("Scaled 2x", larger))
    
    # Scale up 4x
    much_larger = img.resize((img.width * 4, img.height * 4), Image.LANCZOS)
    processed_images.append(("Scaled 4x", much_larger))
    
    return processed_images

def decode_with_preprocessing(image_path):
    """Try decoding with multiple preprocessing techniques."""
    if not PYZBAR_AVAILABLE:
        print("❌ pyzbar not available")
        return None
    
    img = Image.open(image_path)
    print(f"Original image: {img.size[0]}x{img.size[1]}px, mode={img.mode}\n")
    
    # Try all preprocessing variants
    processed = preprocess_image(img)
    
    for name, processed_img in processed:
        print(f"Trying: {name}...", end=" ")
        try:
            decoded = decode(processed_img)
            if decoded:
                print(f"✅ SUCCESS!")
                print(f"\n{'='*60}")
                print(f"BARCODE DECODED SUCCESSFULLY")
                print(f"{'='*60}")
                for obj in decoded:
                    print(f"  Type: {obj.type}")
                    print(f"  Data: {obj.data.decode('utf-8')}")
                    print(f"  Quality: Good (decoded successfully)")
                print(f"{'='*60}\n")
                return decoded
            else:
                print("❌ No barcode found")
        except Exception as e:
            print(f"❌ Error: {e}")
    
    return None

def analyze_image_quality(image_path):
    """Analyze image quality for barcode scanning."""
    img = Image.open(image_path)
    
    print(f"\n{'='*60}")
    print("IMAGE QUALITY ANALYSIS")
    print(f"{'='*60}")
    print(f"Dimensions: {img.size[0]}x{img.size[1]}px")
    print(f"Mode: {img.mode}")
    print(f"Format: {img.format}")
    
    # Convert to grayscale for analysis
    if img.mode == 'RGBA':
        rgb_img = Image.new('RGB', img.size, (255, 255, 255))
        rgb_img.paste(img, mask=img.split()[3])
        img = rgb_img
    
    gray = img.convert('L')
    pixels = list(gray.getdata())
    
    avg_brightness = sum(pixels) / len(pixels)
    min_val = min(pixels)
    max_val = max(pixels)
    contrast = max_val - min_val
    
    print(f"\nBrightness:")
    print(f"  Average: {avg_brightness:.1f}")
    print(f"  Range: {min_val} - {max_val}")
    print(f"  Contrast: {contrast}")
    
    # Recommendations
    print(f"\n Recommendations:")
    if img.size[0] < 200:
        print(f"  ⚠️  Image too small (width: {img.size[0]}px) - recommend 300px minimum")
    else:
        print(f"  ✓ Image size adequate")
    
    if contrast < 100:
        print(f"  ⚠️  Low contrast ({contrast}) - may be difficult to scan")
    else:
        print(f"  ✓ Contrast adequate")
    
    if avg_brightness < 100 or avg_brightness > 200:
        print(f"  ⚠️  Brightness may be suboptimal ({avg_brightness:.1f})")
    else:
        print(f"  ✓ Brightness good")
    
    print(f"{'='*60}\n")

if __name__ == "__main__":
    barcode_image = r"C:/Users/Huzaifa_Haris/.gemini/antigravity/brain/2719e868-dc50-431f-a0ee-18706516ca68/uploaded_media_1770792317718.png"
    
    if not Path(barcode_image).exists():
        print(f"❌ Image not found: {barcode_image}")
        sys.exit(1)
    
    print(f"="*60)
    print(f"ENHANCED BARCODE DECODER")
    print(f"="*60)
    print(f"Analyzing: {Path(barcode_image).name}\n")
    
    # Analyze image quality
    analyze_image_quality(barcode_image)
    
    # Try decoding with preprocessing
    print(f"Attempting decode with preprocessing:\n")
    result = decode_with_preprocessing(barcode_image)
    
    if result:
        print(f"\n✅ RESULT: Barcode is SCANNABLE")
        print(f"   Value: {result[0].data.decode('utf-8')}")
    else:
        print(f"\n❌ RESULT: Could not decode barcode")
        print(f"\n⚠️  Possible issues:")
        print(f"   1. Image resolution too low (current: 280x72px)")
        print(f"   2. Barcode may be truncated or cropped")
        print(f"   3. Image quality degraded during upload/conversion")
        print(f"   4. Barcode format not recognized by decoder")
        print(f"\n💡 Recommendation:")
        print(f"   - Print actual barcode and test with physical scanner")
        print(f"   - Take higher resolution photo (min 600x200px)")
        print(f"   - Ensure entire barcode including quiet zones is visible")
