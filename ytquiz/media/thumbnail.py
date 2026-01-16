from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ytquiz.utils import ensure_dir


def make_long_thumbnail(
    *,
    rng: random.Random,
    bg_image: Path,
    font_file: Path,
    logo_path: Path | None,
    headline: str,
    subline: str,
    out_jpg: Path,
) -> Path:
    ensure_dir(out_jpg.parent)
    w, h = 1280, 720
    img = Image.open(bg_image).convert("RGB")
    img = _fit_cover(img, w, h).filter(ImageFilter.GaussianBlur(radius=8))

    draw = ImageDraw.Draw(img)

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle((0, 0, w, h), fill=(0, 0, 0, 85))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    head_font = ImageFont.truetype(str(font_file), 96)
    sub_font = ImageFont.truetype(str(font_file), 54)

    hx = 70
    hy = 120
    _stroke_text(draw, (hx, hy), headline[:40], head_font, (255, 255, 255), stroke=6)

    sy = hy + 140
    _stroke_text(draw, (hx, sy), subline[:44], sub_font, (255, 255, 255), stroke=5)

    if logo_path is not None and logo_path.exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            max_w = 220
            scale = max_w / max(1, logo.size[0])
            logo = logo.resize((int(logo.size[0] * scale), int(logo.size[1] * scale)))
            lx = w - logo.size[0] - 60
            ly = 60
            img_rgba = img.convert("RGBA")
            img_rgba.alpha_composite(logo, (lx, ly))
            img = img_rgba.convert("RGB")
        except Exception:
            pass

    img.save(out_jpg, format="JPEG", quality=92, optimize=True)
    return out_jpg


def _stroke_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.FreeTypeFont, fill, stroke: int) -> None:
    draw.text(xy, text, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))


def _fit_cover(img: Image.Image, width: int, height: int) -> Image.Image:
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        return img.resize((width, height))
    scale = max(width / iw, height / ih)
    nw = int(iw * scale)
    nh = int(ih * scale)
    img = img.resize((nw, nh))
    x0 = (nw - width) // 2
    y0 = (nh - height) // 2
    return img.crop((x0, y0, x0 + width, y0 + height))
