from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from ..utils.text import wrap_for_display


def _try_font(font_path: str, size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(font_path, size=size)
    except Exception:
        return ImageFont.load_default()


def generate_thumbnail(
    bg_path: Path,
    out_path: Path,
    *,
    headline: str,
    font_bold_path: str,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        base = Image.open(bg_path).convert("RGB")
        thumb = base.resize((1280, 720), resample=Image.Resampling.LANCZOS)
        thumb = thumb.filter(ImageFilter.GaussianBlur(radius=1.2))

        draw = ImageDraw.Draw(thumb)

        headline_wrapped = wrap_for_display(headline, max_chars=18, max_lines=3)

        font = _try_font(font_bold_path, 78)
        small = _try_font(font_bold_path, 46)

        pad = 70
        x = pad
        y = pad

        shadow_offset = 6
        for dx, dy in [(shadow_offset, shadow_offset), (shadow_offset, 0), (0, shadow_offset)]:
            draw.multiline_text((x + dx, y + dy), headline_wrapped, font=font, fill=(0, 0, 0), spacing=8)

        draw.multiline_text((x, y), headline_wrapped, font=font, fill=(255, 255, 255), spacing=8)

        badge = "10s QUIZ"
        bx, by = pad, 720 - 120
        bw, bh = 360, 80
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=22, fill=(0, 0, 0))
        bbox = draw.textbbox((0, 0), badge, font=small)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((bx + (bw - tw) / 2, by + (bh - th) / 2 - 2), badge, font=small, fill=(255, 255, 255))

        thumb.save(out_path, format="PNG", optimize=True)
        return
    except Exception:
        base = Image.open(bg_path).convert("RGB")
        base.resize((1280, 720), resample=Image.Resampling.LANCZOS).save(out_path, format="PNG", optimize=True)
