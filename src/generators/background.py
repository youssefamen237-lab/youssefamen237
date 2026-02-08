from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def generate_background(path: Path, *, width: int = 1080, height: int = 1920, rng: random.Random | None = None) -> None:
    rng = rng or random.Random()
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        c1 = (rng.randint(10, 60), rng.randint(10, 60), rng.randint(10, 60))
        c2 = (rng.randint(160, 230), rng.randint(60, 200), rng.randint(80, 230))
        c3 = (rng.randint(60, 200), rng.randint(120, 240), rng.randint(60, 220))

        img = Image.new("RGB", (width, height), c1)
        draw = ImageDraw.Draw(img)

        for y in range(height):
            t = y / max(1, height - 1)
            r = int(c1[0] * (1 - t) + c2[0] * t)
            g = int(c1[1] * (1 - t) + c2[1] * t)
            b = int(c1[2] * (1 - t) + c2[2] * t)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        overlay = Image.new("RGB", (width, height), c3)
        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=120))
        img = Image.blend(img, overlay, alpha=0.35)

        noise = Image.effect_noise((width, height), rng.uniform(8, 18)).convert("L")
        noise = noise.filter(ImageFilter.GaussianBlur(radius=0.6))
        noise_rgb = Image.merge("RGB", (noise, noise, noise))
        img = Image.blend(img, noise_rgb, alpha=0.08)

        img = img.filter(ImageFilter.GaussianBlur(radius=1.8))
        img.save(path, format="PNG", optimize=True)
        return
    except Exception:
        img = Image.new("RGB", (width, height), (18, 18, 18))
        img.save(path, format="PNG", optimize=True)
