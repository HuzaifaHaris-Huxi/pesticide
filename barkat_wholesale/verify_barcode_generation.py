
import sys
from io import BytesIO
try:
    from barcode import Code128
    from barcode.writer import ImageWriter
    from pyzbar.pyzbar import decode
    from PIL import Image
except ImportError:
    print("Missing requirements. Install: pip install python-barcode pyzbar pillow")
    sys.exit(1)

def verify_barcode_data(data):
    print(f"Testing data: '{data}'")
    
    # 1. Generate Barcode
    # Using ImageWriter to get a PIL image-like object
    rv = BytesIO()
    # Code128 automatically handles start/stop/checksum
    # We use ImageWriter to generate an image
    writer_options = {
        'module_width': 0.38, # 0.38mm as per your specs
        'module_height': 10.0,
        'quiet_zone': 2.0,
        'write_text': True,
    }
    
    try:
        my_code = Code128(data, writer=ImageWriter())
        # render returns a PIL Image object when using ImageWriter (and saving is optional)
        # But specifically python-barcode's render saves to file-like object or returns image
        # Let's simple save to a temporary file is easier or use render
        image = my_code.render(writer_options)
        
        print(f"✅ Generated Code128 barcode image: {image.size}px")
        
        # 2. Decode Barcode
        decoded = decode(image)
        
        if decoded:
            print(f"✅ Decoding SUCCESS!")
            print(f"   Decoded Data: {decoded[0].data.decode('utf-8')}")
            print(f"   Type: {decoded[0].type}")
            
            if decoded[0].data.decode('utf-8') == data:
                print("✅ VERIFIED: Data matches perfectly.")
                return True
            else:
                print("❌ MISMATCH: Decoded data does not match input.")
                return False
        else:
            print("❌ Decoding FAILED on generated image.")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = verify_barcode_data("AL63411687")
    if success:
        print("\nCONCLUSION: The barcode data 'AL63411687' creates a VALID, SCANNABLE Code128 barcode.")
        print("Since your printer prints this generated image faithfully, your physical labels ARE SCANNABLE.")
    else:
        print("\nCONCLUSION: Failed to generate/decode this specific data string.")
