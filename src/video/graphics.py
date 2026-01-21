from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw


def _rand_bg(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size), (random.randint(20, 50), random.randint(20, 50), random.randint(20, 50)))
    draw = ImageDraw.Draw(img)
    for _ in range(18):
        x0 = random.randint(0, size)
        y0 = random.randint(0, size)
        x1 = x0 + random.randint(40, 220)
        y1 = y0 + random.randint(40, 220)
        col = (random.randint(50, 160), random.randint(50, 160), random.randint(50, 160))
        draw.rectangle([x0, y0, x1, y1], outline=col, width=4)
    return img


def _draw_star(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color: Tuple[int, int, int]) -> None:
    pts = []
    for i in range(10):
        ang = math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else int(r * 0.45)
        x = cx + int(math.cos(ang) * rr)
        y = cy - int(math.sin(ang) * rr)
        pts.append((x, y))
    draw.polygon(pts, outline=color, width=6)


def generate_spot_difference_pair(out_dir: str | Path, diff_code: str, *, size: int = 520) -> Tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    left = _rand_bg(size)
    right = left.copy()

    dl = ImageDraw.Draw(left)
    dr = ImageDraw.Draw(right)

    # base shapes
    shapes = []
    for _ in range(6):
        x0 = random.randint(40, size - 160)
        y0 = random.randint(40, size - 160)
        x1 = x0 + random.randint(60, 160)
        y1 = y0 + random.randint(60, 160)
        shapes.append((x0, y0, x1, y1))

    for (x0, y0, x1, y1) in shapes:
        col = (random.randint(120, 240), random.randint(120, 240), random.randint(120, 240))
        dl.ellipse([x0, y0, x1, y1], outline=col, width=6)
        dr.ellipse([x0, y0, x1, y1], outline=col, width=6)

    if diff_code == "STAR":
        _draw_star(dl, size // 2, size // 2, 90, (255, 220, 60))
    elif diff_code == "CIRCLE":
        x0, y0, x1, y1 = random.choice(shapes)
        dl.ellipse([x0, y0, x1, y1], outline=(60, 200, 255), width=10)
        dr.ellipse([x0, y0, x1, y1], outline=(255, 120, 160), width=10)
    elif diff_code == "SQUARE":
        x0, y0, x1, y1 = random.choice(shapes)
        dl.rectangle([x0, y0, x1, y1], outline=(200, 255, 120), width=10)
        # omit in right
    elif diff_code == "TRIANGLE":
        x = random.randint(100, size - 100)
        y = random.randint(100, size - 100)
        pts_left = [(x, y - 90), (x - 80, y + 70), (x + 80, y + 70)]
        pts_right = [(x, y + 90), (x - 80, y - 70), (x + 80, y - 70)]
        dl.polygon(pts_left, outline=(255, 255, 255), width=8)
        dr.polygon(pts_right, outline=(255, 255, 255), width=8)
    else:  # DOT
        x = random.randint(80, size - 80)
        y = random.randint(80, size - 80)
        dl.ellipse([x - 16, y - 16, x + 16, y + 16], fill=(255, 255, 255))
        dr.ellipse([x + 40 - 16, y - 16, x + 40 + 16, y + 16], fill=(255, 255, 255))

    left_path = out_dir / f"spot_left_{random.randint(1000,9999)}.png"
    right_path = out_dir / f"spot_right_{random.randint(1000,9999)}.png"
    left.save(left_path, format="PNG")
    right.save(right_path, format="PNG")
    return left_path, right_path
