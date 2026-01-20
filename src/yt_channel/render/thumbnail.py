from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont


@dataclass(frozen=True)
class ThumbnailStyle:
    font_bold: Path
    font_regular: Path
    box_color_rgba: Tuple[int, int, int, int] = (0, 0, 0, 170)


def _fit_cover(img: Image.Image, size: Tuple[int, int]) -> Image.Image:
    tw, th = size
    iw, ih = img.size
    scale = max(tw / iw, th / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh))
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def make_long_thumbnail(
    *,
    out_path: Path,
    bg_image: Path,
    title_text: str,
    style: ThumbnailStyle,
    rng: random.Random,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    base = Image.open(bg_image).convert("RGB")
    base = _fit_cover(base, (1280, 720))
    base = base.filter(ImageFilter.GaussianBlur(radius=6))
    base_rgba = base.convert("RGBA")

    overlay = Image.new("RGBA", base_rgba.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Dark box area
    margin = 70
    box = (margin, 120, 1280 - margin, 720 - 120)
    draw.rounded_rectangle(box, radius=40, fill=style.box_color_rgba)

    # Text
    font_big = ImageFont.truetype(str(style.font_bold), 86)
    font_small = ImageFont.truetype(str(style.font_regular), 44)

    headline = title_text.strip()
    if len(headline) > 42:
        headline = headline[:42].rstrip() + "…"

    sub = rng.choice([
        "Play along & keep score!",
        "How many can you get right?",
        "Try to beat your best score!",
        "New episode — test your knowledge",
    ])

    # Wrap headline into 2 lines max
    words = headline.split()
    lines = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 <= 20:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur)
            cur = w
        if len(lines) >= 2:
            break
    if cur and len(lines) < 2:
        lines.append(cur)

    y = 210
    for line in lines:
        tw, th = draw.textsize(line, font=font_big)
        draw.text(((1280 - tw) / 2, y), line, font=font_big, fill=(255, 255, 255, 255))
        y += th + 10

    tw, th = draw.textsize(sub, font=font_small)
    draw.text(((1280 - tw) / 2, 560), sub, font=font_small, fill=(255, 213, 74, 255))

    out = Image.alpha_composite(base_rgba, overlay).convert("RGB")
    out.save(out_path, format="JPEG", quality=92, optimize=True)
