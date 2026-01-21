from __future__ import annotations

import random
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont


def _find_font() -> Optional[str]:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def generate_thumbnail(
    *,
    title: str,
    out_path: str | Path,
    background_image: Optional[str | Path] = None,
    size: Tuple[int, int] = (1280, 720),
) -> Path:
    w, h = size
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if background_image and Path(background_image).exists():
        bg = Image.open(background_image).convert("RGB")
        bg = bg.resize((w, h))
    else:
        bg = Image.new("RGB", (w, h), (20, 20, 20))
        draw = ImageDraw.Draw(bg)
        for _ in range(24):
            x0 = random.randint(-200, w)
            y0 = random.randint(-200, h)
            x1 = x0 + random.randint(200, 700)
            y1 = y0 + random.randint(200, 700)
            col = (random.randint(30, 90), random.randint(30, 90), random.randint(30, 90))
            draw.rectangle([x0, y0, x1, y1], outline=col, width=8)

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([40, 60, w - 40, h - 60], fill=(0, 0, 0, 130))

    font_path = _find_font()
    if font_path:
        font = ImageFont.truetype(font_path, 78)
        font2 = ImageFont.truetype(font_path, 56)
    else:
        font = ImageFont.load_default()
        font2 = ImageFont.load_default()

    title = title.strip()
    if len(title) > 60:
        title = title[:57].rstrip() + "…"

    # Simple word wrap
    words = title.split()
    lines = []
    current = ""
    for w0 in words:
        test = (current + " " + w0).strip()
        if len(test) <= 18:
            current = test
        else:
            if current:
                lines.append(current)
            current = w0
    if current:
        lines.append(current)
    lines = lines[:3]

    y = 140
    for i, line in enumerate(lines):
        f = font if i == 0 else font2
        tw, th = od.textbbox((0, 0), line, font=f)[2:]
        od.text(((w - tw) / 2, y), line, font=f, fill=(255, 255, 255, 255), stroke_width=6, stroke_fill=(0, 0, 0, 230))
        y += th + 18

    final = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    final.save(out, format="JPEG", quality=92)
    return out
