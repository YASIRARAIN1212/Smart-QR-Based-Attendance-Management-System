from PIL import Image, ImageDraw, ImageFont, ImageFilter
import random
import string
import io
import base64
import hashlib

def generate_captcha_code(length=6):
    """Generate a random CAPTCHA code"""
    chars = string.ascii_uppercase + string.digits
    chars = chars.replace('O', '').replace('0', '').replace('I', '').replace('1', '')
    return ''.join(random.choice(chars) for _ in range(length))

def generate_captcha_image(code):
    """Generate a CAPTCHA image from the given code"""
    width = 280
    height = 80
    
    # Create image with gradient background
    image = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(image)
    
    # Dark gradient background
    for i in range(height):
        color_value = int(40 + (i / height) * 20)
        draw.rectangle(((0, i), (width, i+1)), fill=(color_value, 0, 0))
    
    # Add noise lines
    for _ in range(3):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        draw.line([(x1, y1), (x2, y2)], fill=(100, 100, 0), width=2)
    
    # Try to load a font, fall back to default if not available
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
    except:
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except:
            font = ImageFont.load_default()
    
    # Draw each character with slight variations
    x_start = 20
    for i, char in enumerate(code):
        # Random color (yellow-ish)
        color = (
            random.randint(200, 255),
            random.randint(180, 220),
            random.randint(0, 50)
        )
        
        # Random position variation
        x = x_start + i * 40 + random.randint(-5, 5)
        y = random.randint(10, 20)
        
        # Random rotation (slight)
        angle = random.randint(-15, 15)
        
        # Create temporary image for rotated text
        char_img = Image.new('RGBA', (60, 60), (255, 255, 255, 0))
        char_draw = ImageDraw.Draw(char_img)
        char_draw.text((10, 5), char, font=font, fill=color)
        
        # Rotate and paste
        rotated = char_img.rotate(angle, expand=False, fillcolor=(255, 255, 255, 0))
        image.paste(rotated, (x, y), rotated)
    
    # Add noise dots
    for _ in range(100):
        x = random.randint(0, width-1)
        y = random.randint(0, height-1)
        draw.point((x, y), fill=(random.randint(100, 150), random.randint(100, 150), random.randint(0, 50)))
    
    # Slight blur for anti-aliasing
    image = image.filter(ImageFilter.SMOOTH)
    
    # Return raw PNG bytes for serving via Flask route
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    buffered.seek(0)
    return buffered.getvalue()

def hash_captcha_code(code):
    """Hash the CAPTCHA code for secure storage"""
    return hashlib.sha256(code.upper().encode()).hexdigest()

def verify_captcha(user_input, hashed_code):
    """Verify user's CAPTCHA input"""
    if not user_input or not hashed_code:
        return False
    return hash_captcha_code(user_input.upper()) == hashed_code
