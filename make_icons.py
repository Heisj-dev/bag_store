"""
Makes the two site icons from the logo that is already in your project.

Run it once, from the folder that contains manage.py, with your virtual
environment on (the same one you use for runserver):

    python make_icons.py

It reads the logo:    store/static/store/images/bag-store-logo.png
and writes these two: store/static/store/images/favicon.ico
                      store/static/store/images/apple-touch-icon.png

Both are made from the pink bag in the logo. Running it again simply makes
them again, so it is safe to run twice. You can delete this file afterwards.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent          # the folder that contains manage.py

IMAGES = ROOT / "store" / "static" / "store" / "images"

LOGO = IMAGES / "bag-store-logo.png"

CREAM = (242, 241, 237, 255)       # the site's background colour, #f2f1ed


def find_bag(logo):
    """Cut the pink shopping-bag mark out of the logo."""

    pixels = logo.load()
    width, height = logo.size

    left, top, right, bottom = width, height, -1, -1

    for y in range(height):
        for x in range(width):

            red, green, blue, alpha = pixels[x, y]

            if alpha > 200 and red > 170 and green < 90 and 40 < blue < 150:
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)

    if right < 0:
        raise SystemExit("Could not find the pink bag in bag-store-logo.png")

    # a few pixels of margin, so the soft edge of the bag is kept
    return logo.crop((
        max(left - 3, 0),
        max(top - 3, 0),
        min(right + 4, width),
        min(bottom + 4, height),
    ))


def on_square(bag, size, fill, background):
    """The bag, centred on a square, filling `fill` of its width or height."""

    square = Image.new("RGBA", (size, size), background)

    scale = size * fill / max(bag.size)

    width = round(bag.width * scale)
    height = round(bag.height * scale)

    mark = bag.resize((width, height), Image.Resampling.LANCZOS)

    square.alpha_composite(mark, ((size - width) // 2, (size - height) // 2))

    return square


if not LOGO.is_file():
    raise SystemExit(f"Could not find the logo at {LOGO}")

bag = find_bag(Image.open(LOGO).convert("RGBA"))

# The tab icon: one file holding 16, 32 and 48 pixel versions.
favicon = IMAGES / "favicon.ico"

on_square(bag, 512, 0.94, (0, 0, 0, 0)).save(
    favicon, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)]
)

# The iPhone home-screen icon: 180 x 180, on the site's cream background
# (an iPhone fills see-through areas with black).
touch_icon = IMAGES / "apple-touch-icon.png"

on_square(bag, 180, 0.60, CREAM).convert("RGB").save(
    touch_icon, format="PNG", optimize=True
)

for icon in (favicon, touch_icon):
    print(f"Made {icon.relative_to(ROOT)}  ({icon.stat().st_size} bytes)")