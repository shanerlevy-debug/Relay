"""Generate a 512x512 Relay app icon: lowercase white 'r' on a red field."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SIZE = 512
BG = (220, 38, 38)       # Tailwind red-600 — punchy, not too crimson
FG = (255, 255, 255)
OUT = Path(__file__).resolve().parents[1] / "relay-logo-512.png"

img = Image.new("RGB", (SIZE, SIZE), BG)
draw = ImageDraw.Draw(img)

font = None
for path in [
    r"C:\Windows\Fonts\ariblk.ttf",   # Arial Black — bold, geometric
    r"C:\Windows\Fonts\arialbd.ttf",  # Arial Bold fallback
    r"C:\Windows\Fonts\segoeuib.ttf", # Segoe UI Bold fallback
]:
    try:
        font = ImageFont.truetype(path, 380)
        print(f"using font: {path}")
        break
    except OSError:
        continue
if font is None:
    raise SystemExit("no usable TrueType font found in C:\\Windows\\Fonts")

text = "r"
bbox = draw.textbbox((0, 0), text, font=font)
text_w = bbox[2] - bbox[0]
text_h = bbox[3] - bbox[1]
x = (SIZE - text_w) // 2 - bbox[0]
y = (SIZE - text_h) // 2 - bbox[1]

draw.text((x, y), text, fill=FG, font=font)
img.save(OUT, "PNG")
print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
