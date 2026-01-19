from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from yt_auto.config import Config
from yt_auto.utils import ensure_dir


def build_long_thumbnail(
    cfg: Config,
    bg_image: Path,
    out_jpg: Path,
    *,
    keyword: str,
    badge: str,
    subline: str = "",
    seed: int = 0,
) -> None:
    """Create a more varied long-video thumbnail.

    الهدف: تجنّب شكل مكرر (نفس عنوان + نفس Thumbnail) عبر قوالب متعددة.
    """

    ensure_dir(out_jpg.parent)

    r = random.Random(seed if seed else random.randint(1, 10**9))

    base = Image.open(bg_image).convert("RGB")
    base = base.resize((1280, 720))

    # Vary blur + contrast slightly between runs
    blur_radius = r.choice([6, 8, 10, 12, 14])
    base = base.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    # Add a subtle dark overlay for readability
    overlay = Image.new("RGBA", (1280, 720), (0, 0, 0, r.choice([70, 85, 95, 110])))
    base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGBA")

    draw = ImageDraw.Draw(base)

    keyword = (keyword or "").strip().upper() or "QUIZ"
    badge = (badge or "").strip().upper() or "CHALLENGE"
    subline = (subline or "").strip().upper()

    # Pick a layout template
    layout = r.randint(0, 2)

    # Fonts
    font_kw = ImageFont.truetype(cfg.fontfile, r.choice([120, 132, 144, 156]))
    font_badge = ImageFont.truetype(cfg.fontfile, 56)
    font_sub = ImageFont.truetype(cfg.fontfile, 44)
    font_brand = ImageFont.truetype(cfg.fontfile, 40)

    # Accent colors (high-contrast palettes)
    accent = r.choice(
        [
            (255, 215, 0, 235),  # gold
            (0, 255, 200, 230),  # cyan
            (255, 80, 80, 235),  # red
            (120, 200, 255, 230),  # blue
        ]
    )

    # Helper to draw outlined text
    def _text(xy: tuple[int, int], txt: str, font: ImageFont.FreeTypeFont, fill=(255, 255, 255, 255), stroke=8):
        draw.text(xy, txt, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0, 255))

    # Helper to draw a rounded badge
    def _badge_rect(x1: int, y1: int, x2: int, y2: int, color):
        rad = 24
        draw.rounded_rectangle([x1, y1, x2, y2], radius=rad, fill=color)

    # Layouts
    if layout == 0:
        # Big keyword centered
        kw_w, kw_h = draw.textbbox((0, 0), keyword, font=font_kw)[2:]
        kw_x = (1280 - kw_w) // 2
        kw_y = r.choice([210, 230, 250])
        _text((kw_x, kw_y), keyword, font_kw, stroke=10)

        if subline:
            sub_w, sub_h = draw.textbbox((0, 0), subline, font=font_sub)[2:]
            sub_x = (1280 - sub_w) // 2
            sub_y = kw_y + kw_h + 16
            _text((sub_x, sub_y), subline, font_sub, fill=(255, 255, 255, 235), stroke=6)

        # Badge top-right
        b_w, b_h = draw.textbbox((0, 0), badge, font=font_badge)[2:]
        pad_x = 34
        pad_y = 20
        x2 = 1280 - 46
        y1 = 56
        x1 = x2 - b_w - pad_x * 2
        y2 = y1 + b_h + pad_y * 2
        _badge_rect(x1, y1, x2, y2, accent)
        draw.text((x1 + pad_x, y1 + pad_y - 2), badge, font=font_badge, fill=(0, 0, 0, 255))

    elif layout == 1:
        # Keyword left + badge bottom-right
        kw_x = 72
        kw_y = r.choice([180, 210, 240])
        _text((kw_x, kw_y), keyword, font_kw, stroke=10)

        if subline:
            _text((kw_x, kw_y + 170), subline, font_sub, fill=(255, 255, 255, 235), stroke=6)

        b_w, b_h = draw.textbbox((0, 0), badge, font=font_badge)[2:]
        pad_x = 34
        pad_y = 20
        x2 = 1280 - 56
        y2 = 720 - 62
        x1 = x2 - b_w - pad_x * 2
        y1 = y2 - b_h - pad_y * 2
        _badge_rect(x1, y1, x2, y2, accent)
        draw.text((x1 + pad_x, y1 + pad_y - 2), badge, font=font_badge, fill=(0, 0, 0, 255))

    else:
        # Keyword top + badge center
        kw_w, kw_h = draw.textbbox((0, 0), keyword, font=font_kw)[2:]
        kw_x = (1280 - kw_w) // 2
        kw_y = 120
        _text((kw_x, kw_y), keyword, font_kw, stroke=10)

        b_w, b_h = draw.textbbox((0, 0), badge, font=font_badge)[2:]
        pad_x = 40
        pad_y = 24
        x1 = (1280 - (b_w + pad_x * 2)) // 2
        y1 = 360
        x2 = x1 + b_w + pad_x * 2
        y2 = y1 + b_h + pad_y * 2
        _badge_rect(x1, y1, x2, y2, accent)
        draw.text((x1 + pad_x, y1 + pad_y - 2), badge, font=font_badge, fill=(0, 0, 0, 255))

        if subline:
            sub_w, sub_h = draw.textbbox((0, 0), subline, font=font_sub)[2:]
            sub_x = (1280 - sub_w) // 2
            sub_y = y2 + 26
            _text((sub_x, sub_y), subline, font_sub, fill=(255, 255, 255, 235), stroke=6)

    # Small brand mark (kept subtle)
    brand = "QUIZZARO"
    draw.text((60, 650), brand, font=font_brand, fill=(255, 255, 255, 180), stroke_width=5, stroke_fill=(0, 0, 0, 220))

    base.convert("RGB").save(out_jpg, quality=92)
