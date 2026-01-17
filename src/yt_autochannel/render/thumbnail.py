from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..utils.text_utils import sanitize_text, wrap_lines


def create_long_thumbnail(
    bg_path: Path,
    title: str,
    out_path: Path,
    font_path: str,
    primary: str,
    secondary: str,
    accent: str,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = 1280, 720
    im = Image.open(bg_path).convert("RGBA")
    im = im.resize((w, h))
    draw = ImageDraw.Draw(im)

    # dark overlay
    draw.rectangle([0, 0, w, h], fill=(0, 0, 0, 120))

    # font
    try:
        font_big = ImageFont.truetype(font_path, 68)
        font_small = ImageFont.truetype(font_path, 40)
    except Exception:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()

    title = sanitize_text(title)
    wrapped = wrap_lines(title, width=22)

    # accent bar
    draw.rectangle([0, h - 80, w, h], fill=accent)

    # text
    x = 70
    y = 110
    draw.text((x, y), "TRIVIA CHALLENGE", font=font_small, fill=secondary)
    y += 70
    for line in wrapped.split("\n"):
        draw.text((x, y), line, font=font_big, fill=primary)
        y += 78

    # corner badge
    badge_w, badge_h = 320, 90
    badge_x, badge_y = w - badge_w - 40, 40
    draw.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], radius=22, fill=(0, 0, 0, 180))
    draw.text((badge_x + 25, badge_y + 22), "NEW EPISODE", font=font_small, fill=secondary)

    im.convert("RGB").save(out_path, format="JPEG", quality=92)
