"""Trim the empty bottom of the README's panel screenshots (docs/images/panel_*.png), in place.

Usage (needs Pillow):  uv run --with pillow python tools/crop_panel_shots.py
"""
import os

from PIL import Image, ImageChops

d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "images")
for name in ("panel_fallback.png", "panel_driver.png"):
    p = os.path.join(d, name)
    im = Image.open(p).convert("RGB")
    bg = Image.new("RGB", im.size, im.getpixel((im.width - 1, im.height - 1)))
    box = ImageChops.difference(im, bg).getbbox()
    im.crop((0, 0, im.width, min(im.height, box[3] + 10))).save(p, optimize=True)
    print(name, Image.open(p).size)
