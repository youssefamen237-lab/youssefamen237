"""
templates/visual_question.py – Quizzaro Visual Question Template
================================================================
Uses the B-roll background as the visual question subject — the blurred
background is partially un-blurred in a spotlight circle to draw attention
to the visual element, then the question overlays it.

Unique visual hooks:
  - 👁 VISUAL QUIZ badge with rose/pink palette
  - Circular spotlight vignette that "zooms in" on the subject
  - Semi-transparent frosted card behind question text
  - "Look carefully…" sub-label fades in
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
BADGE_COLOR = (200, 30, 90, 230)


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


def _draw_spotlight(img: Image.Image, cx: int, cy: int, radius: int) -> Image.Image:
    """
    Draw a radial vignette: darker at edges, lighter near centre.
    Simulates spotlight focus on the visual subject.
    """
    vignette = Image.new("RGBA", img.size, (0, 0, 0, 0))
    vd       = ImageDraw.Draw(vignette)
    # Draw concentric semi-transparent rings from edge to centre
    steps = 18
    for i in range(steps, 0, -1):
        r     = int(radius * i / steps * 2.4)
        alpha = int(170 * (1 - (steps - i) / steps) ** 1.5)
        vd.ellipse([cx - r, cy - r, cx + r, cy + r],
                   fill=(0, 0, 0, alpha))
    # Clear the centre spot
    vd.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
               fill=(0, 0, 0, 0))
    return Image.alpha_composite(img.convert("RGBA"), vignette).convert("RGB")


def draw_question_phase(img: Image.Image, question_text: str, cta_text: str,
                        frame_idx: int, popup_scale: float, popup_alpha: int) -> Image.Image:
    from video.text_animator import wrap_text

    cx = WIDTH // 2

    # Apply spotlight to upper half of image (visual subject area)
    if frame_idx > 5:
        spotlight_radius = min(320, 160 + frame_idx * 4)
        img = _draw_spotlight(img, cx, HEIGHT // 3, spotlight_radius)

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)

    # Badge
    bf = _best_font(38)
    draw.rounded_rectangle([cx - 175, SAFE_TOP + 18, cx + 175, SAFE_TOP + 74],
                            radius=24, fill=BADGE_COLOR)
    draw.text((cx, SAFE_TOP + 46), "👁 VISUAL QUIZ", font=bf,
              fill=(255, 255, 255, 255), anchor="mm")

    # Sub-label
    if frame_idx > 10:
        sf = _best_font(30)
        draw.text((cx, SAFE_TOP + 98), "Look carefully…", font=sf,
                  fill=(255, 150, 200, 190), anchor="mm")

    # Frosted card behind question
    card_y1 = int(HEIGHT * 0.56)
    card_y2 = int(HEIGHT * 0.82)
    draw.rounded_rectangle([SAFE_LEFT - 10, card_y1, SAFE_RIGHT + 10, card_y2],
                            radius=22, fill=(0, 0, 0, 150))

    # Animated question
    q_size = max(12, int(62 * popup_scale))
    qf     = _best_font(q_size)
    lines  = wrap_text(question_text, qf, SAFE_W - 30)
    total_h = len(lines) * (q_size + 14)
    start_y = (card_y1 + card_y2) // 2 - total_h // 2 - 30
    _multiline(draw, lines, cx, start_y, qf,
               fill=(255, 255, 255, popup_alpha), stroke=5)

    # CTA
    if frame_idx > 18:
        cf = _best_font(28)
        for i, line in enumerate(wrap_text(cta_text, cf, SAFE_W - 40)):
            draw.text((cx, card_y2 - 60 + i * 36), line, font=cf,
                      fill=(255, 160, 200, 200), anchor="mm")

    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def draw_answer_phase(img: Image.Image, correct_answer: str, explanation: str,
                      reveal_frame: int) -> Image.Image:
    from video.text_animator import wrap_text
    from PIL import ImageFilter

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)
    cx    = WIDTH // 2

    af    = _best_font(70 if len(correct_answer) < 18 else 52)
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
    by1 = HEIGHT // 2 - 210
    d2.rounded_rectangle([cx - 200, by1, cx + 200, by1 + 74],
                          radius=26, fill=BADGE_COLOR)
    d2.text((cx, by1 + 37), "👁 CORRECT!", font=bf,
            fill=(255, 255, 255, 255), anchor="mm")

    if explanation and reveal_frame > 12:
        ef = _best_font(28)
        for i, line in enumerate(wrap_text(explanation, ef, SAFE_W - 40)[:2]):
            d2.text((cx, HEIGHT // 2 + 190 + i * 38), line, font=ef,
                    fill=(190, 190, 190, 200), anchor="mm")

    return Image.alpha_composite(base.convert("RGBA"), l2).convert("RGB")
