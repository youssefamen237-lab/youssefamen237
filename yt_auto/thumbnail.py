from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from yt_auto.config import Config
from yt_auto.utils import ensure_dir


def build_long_thumbnail(cfg: Config, bg_image: Path, out_jpg: Path, date_yyyymmdd: str) -> None:
    ensure_dir(out_jpg.parent)

    base = Image.open(bg_image).convert("RGB")
    base = base.resize((1280, 720))
    base = base.filter(ImageFilter.GaussianBlur(radius=10))

    draw = ImageDraw.Draw(base)

    font_big = ImageFont.truetype(cfg.fontfile, 78)
    font_small = ImageFont.truetype(cfg.fontfile, 46)

    title = "Quizzaro Compilation"
    subtitle = date_yyyymmdd

    _center_text(draw, (640, 300), title, font_big)
    _center_text(draw, (640, 400), subtitle, font_small)

    base.save(out_jpg, quality=92)


def _center_text(draw: ImageDraw.ImageDraw, center: tuple[int, int], text: str, font: ImageFont.FreeTypeFont) -> None:
    w, h = draw.textbbox((0, 0), text, font=font)[2:]
    x = int(center[0] - w / 2)
    y = int(center[1] - h / 2)
    draw.rectangle([x - 28, y - 18, x + w + 28, y + h + 18], fill=(0, 0, 0, 160))
    draw.text((x, y), text, font=font, fill=(255, 255, 255))
