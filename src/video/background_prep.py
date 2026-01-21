from __future__ import annotations

import random
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageFilter


def _cover_resize(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    w, h = img.size
    scale = max(target_w / w, target_h / h)
    nw = int(w * scale)
    nh = int(h * scale)
    img = img.resize((nw, nh), resample=Image.LANCZOS)
    left = (nw - target_w) // 2
    top = (nh - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def prepare_blurred_background(
    src_path: str | Path,
    *,
    out_path: str | Path,
    width: int,
    height: int,
    blur_sigma: float,
) -> Path:
    src_path = Path(src_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    img = Image.open(src_path).convert("RGB")
    img = _cover_resize(img, width, height)

    # PIL GaussianBlur uses radius; approximate sigma->radius
    radius = max(0.0, float(blur_sigma) / 4.0)
    if radius > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=radius))

    # Add tiny noise to reduce banding / make it feel less static
    if random.random() < 0.35:
        px = img.load()
        for _ in range(4000):
            x = random.randint(0, width - 1)
            y = random.randint(0, height - 1)
            r, g, b = px[x, y]
            px[x, y] = (max(0, min(255, r + random.randint(-6, 6))),
                        max(0, min(255, g + random.randint(-6, 6))),
                        max(0, min(255, b + random.randint(-6, 6))))
    img.save(out, format="JPEG", quality=88)
    return out
