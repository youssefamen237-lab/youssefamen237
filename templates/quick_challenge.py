"""
templates/quick_challenge.py – Quizzaro Quick Challenge Template
================================================================
High-energy format with a flashing "CHALLENGE" badge, bold question,
and a pulsing ring effect around the timer to create urgency.

Unique visual hooks:
  - ⚡ lightning badge pulses (alternates opacity every 4 frames)
  - "YOU HAVE 5 SECONDS!" sub-headline
  - Yellow/orange colour palette (contrasts with other templates)
"""

from __future__ import annotations

import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH, HEIGHT = 1080, 1920
SAFE_LEFT  = int(WIDTH * 0.08)
SAFE_RIGHT = int(WIDTH * 0.92)
SAFE_TOP   = int(HEIGHT * 0.12)
SAFE_W     = SAFE_RIGHT - SAFE_LEFT
PHOSPHOR   = (57, 255, 20, 255)
BADGE_COLOR_A = (255, 140, 0, 230)
BADGE_COLOR_B = (255, 60, 0, 230)


def _best_font(size):
    for p in ["data/fonts/montserrat_extrabold.ttf",
              "data/fonts/montserrat_bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _multiline(draw, lines, cx, start_y, font, fill, spacing=14, stroke=5):
    for i, line in enumerate(lines):
        y = start_y + i * (font.size + spacing)
        if stroke:
            for dx in range(-stroke, stroke + 1):
                for dy in range(-stroke, stroke + 1):
                    if dx or dy:
                        draw.text((cx + dx, y + dy), line, font=font,
                                  fill=(0, 0, 0, 255), anchor="mm")
        draw.text((cx, y), line, font=font, fill=fill, anchor="mm")


def draw_question_phase(img: Image.Image, question_text: str, cta_text: str,
                        frame_idx: int, popup_scale: float, popup_alpha: int) -> Image.Image:
    from video.text_animator import wrap_text

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)
    cx    = WIDTH // 2

    # Pulsing badge
    pulse = BADGE_COLOR_A if (frame_idx // 4) % 2 == 0 else BADGE_COLOR_B
    bf    = _best_font(40)
    draw.rounded_rectangle([cx - 195, SAFE_TOP + 18, cx + 195, SAFE_TOP + 74],
                            radius=26, fill=pulse)
    draw.text((cx, SAFE_TOP + 46), "⚡ QUICK CHALLENGE", font=bf,
              fill=(255, 255, 255, 255), anchor="mm")

    # Sub-headline
    if frame_idx > 10:
        sf = _best_font(34)
        draw.text((cx, SAFE_TOP + 100), "YOU HAVE 5 SECONDS!", font=sf,
                  fill=(255, 220, 60, 200), anchor="mm")

    # Animated question
    q_size = max(12, int(70 * popup_scale))
    qf     = _best_font(q_size)
    lines  = wrap_text(question_text, qf, SAFE_W - 20)
    total_h = len(lines) * (q_size + 14)
    start_y = HEIGHT // 2 - 100 - total_h // 2
    _multiline(draw, lines, cx, start_y, qf,
               fill=(255, 255, 255, popup_alpha), stroke=6)

    # CTA
    if frame_idx > 18:
        cf = _best_font(30)
        for i, line in enumerate(wrap_text(cta_text, cf, SAFE_W - 40)):
            draw.text((cx, HEIGHT // 2 + 80 + i * 38), line, font=cf,
                      fill=(255, 200, 60, 200), anchor="mm")

    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def draw_answer_phase(img: Image.Image, correct_answer: str, explanation: str,
                      reveal_frame: int) -> Image.Image:
    from video.text_animator import wrap_text
    from PIL import ImageFilter

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)
    cx    = WIDTH // 2

    af    = _best_font(72 if len(correct_answer) < 18 else 54)
    glow  = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd    = ImageDraw.Draw(glow)
    lines = wrap_text(correct_answer, af, SAFE_W - 30)
    _multiline(gd, lines, cx, HEIGHT // 2 + 60, af, PHOSPHOR, stroke=0)
    glow  = glow.filter(ImageFilter.GaussianBlur(radius=18))

    sharp = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd    = ImageDraw.Draw(sharp)
    _multiline(sd, lines, cx, HEIGHT // 2 + 60, af, PHOSPHOR, stroke=6)

    base  = Image.alpha_composite(img.convert("RGBA"), glow)
    base  = Image.alpha_composite(base, sharp).convert("RGB")

    l2 = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d2 = ImageDraw.Draw(l2)
    bf = _best_font(50)
    by1 = HEIGHT // 2 - 215
    d2.rounded_rectangle([cx - 195, by1, cx + 195, by1 + 72],
                          radius=26, fill=(57, 255, 20, 220))
    d2.text((cx, by1 + 36), "⚡ CORRECT!", font=bf,
            fill=(0, 0, 0, 255), anchor="mm")

    if explanation and reveal_frame > 12:
        ef = _best_font(28)
        for i, line in enumerate(wrap_text(explanation, ef, SAFE_W - 40)[:2]):
            d2.text((cx, HEIGHT // 2 + 190 + i * 38), line, font=ef,
                    fill=(190, 190, 190, 200), anchor="mm")

    return Image.alpha_composite(base.convert("RGBA"), l2).convert("RGB")
