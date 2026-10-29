"""Draw the module icon (a cube with an orbit arrow), 128 x 128 PNG.

Usage (needs Pillow):  uv run --with pillow python tools/make_icon.py MouseNav3D/Resources/Icons/MouseNav3D.png
"""
import math
import sys

from PIL import Image, ImageDraw

N = 512
im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle((16, 16, N - 16, N - 16), radius=96, fill=(31, 78, 140, 255))
# isometric cube
cx, cy, r = 256, 230, 130
def pt(a): return (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
top = [pt(-90), pt(-30), (cx, cy), pt(-150)]
left = [pt(-150), (cx, cy), (cx, cy + r), pt(150)]
right = [pt(-30), pt(30), (cx, cy + r), (cx, cy)]
d.polygon(top, fill=(232, 240, 250, 255))
d.polygon(left, fill=(150, 185, 225, 255))
d.polygon(right, fill=(98, 142, 200, 255))
for poly in (top, left, right):
    d.line(poly + [poly[0]], fill=(31, 78, 140, 255), width=8, joint="curve")
# orbit arc around the base (rotation cue) with an arrow head
box = (86, 300, N - 86, 470)
d.arc(box, start=200, end=340, fill=(255, 200, 70, 255), width=18)
ex = (box[0] + box[2]) / 2 + (box[2] - box[0]) / 2 * math.cos(math.radians(340))
ey = (box[1] + box[3]) / 2 + (box[3] - box[1]) / 2 * math.sin(math.radians(340))
d.polygon([(ex - 4, ey - 44), (ex + 46, ey + 2), (ex - 26, ey + 24)], fill=(255, 200, 70, 255))
im.resize((128, 128), Image.LANCZOS).save(sys.argv[1], optimize=True)
