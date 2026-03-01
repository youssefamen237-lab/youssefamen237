"""
templates/true_false.py – Quizzaro True/False Template
=======================================================
Renders the visual layout specific to the True/False question format.

Layout:
  ┌─────────────────────────────┐
  │  [TRUE OR FALSE? badge]     │
  │                             │
  │   Question text (pop-up)    │
  │                             │
  │   CTA text                  │
  │                             │
  │  [  TRUE  ]  [  FALSE  ]    │  ← Two large coloured buttons
  └─────────────────────────────┘

During the answer phase the correct button glows phosphor green.
Wrong button fades to dark red.

All drawing functions receive a PIL Image and return it.
Called by video/video_composer.py during frame rendering.
"""

from __future__ import annotations

import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Canvas constants (must match video_composer.py)
WIDTH, HEIGHT = 1080, 1920
SAFE_LEFT = int(WIDTH * 0.08)
SAFE_RIGHT = int(WIDTH * 0.92)
SAFE_TOP = int(HEIGHT * 0.12)
SAFE_W = SAFE_RIGHT - SAFE_LEFT

# Button geometry
BTN_Y1 = int(HEIGHT * 0.62)
BTN_Y2 = int(HEIGHT * 0.72)
BTN_GAP = 24
BTN_MID = WIDTH // 2
BTN_RADIUS = 26

# Colours
TRUE_COLOR  = (0, 200, 80, 220)
FALSE_COLOR = (210, 40, 40, 220)
CORRECT_GLOW = (57, 255, 20, 255)
WRONG_DIM    = (80, 20, 20, 180)
LABEL_WHITE  = (255, 255, 255, 255)
BADGE_COLOR  = (255, 200, 0, 220)
BLACK_STROKE = (0, 0, 0, 255)


def _best_font(size: int) -> ImageFont.FreeTypeFont:
    for path in [
        "data/fonts/montserrat_extrabold.ttf",
        "data/fonts/montserrat_bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _stroke_text(draw: ImageDraw.Draw, pos, text: str, font, fill, stroke: int = 5) -> None:
    sx, sy = pos
    for dx in range(-stroke, stroke + 1):
        for dy in range(-stroke, stroke + 1):
            if dx or dy:
                draw.text((sx + dx, sy + dy), text, font=font,
                          fill=BLACK_STROKE, anchor="mm")
    draw.text((sx, sy), text, font=font, fill=fill, anchor="mm")


def draw_question_phase(img: Image.Image, question_text: str, cta_text: str,
                        frame_idx: int, popup_scale: float, popup_alpha: int) -> Image.Image:
    """
    Draw badge + animated question text + CTA + TRUE/FALSE buttons.
    popup_scale: 0.0→1.0 cubic ease-out for the pop-up animation.
    """
    from video.text_animator import wrap_text

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx = WIDTH // 2

    # Badge
    bf = _best_font(38)
    draw.rounded_rectangle([cx - 175, SAFE_TOP + 20, cx + 175, SAFE_TOP + 72],
                            radius=24, fill=BADGE_COLOR)
    draw.text((cx, SAFE_TOP + 46), "TRUE OR FALSE?", font=bf,
              fill=(0, 0, 0, 255), anchor="mm")

    # Animated question text
    q_size = max(12, int(68 * popup_scale))
    qf = _best_font(q_size)
    lines = wrap_text(question_text, qf, SAFE_W - 20)
    line_h = q_size + 14
    total_h = len(lines) * line_h
    start_y = HEIGHT // 2 - 110 - total_h // 2
    for i, line in enumerate(lines):
        y = start_y + i * line_h
        _stroke_text(draw, (cx, y), line, qf,
                     fill=(255, 255, 255, popup_alpha), stroke=5)

    # CTA (appears after frame 18)
    if frame_idx > 18:
        cf = _best_font(30)
        cta_lines = wrap_text(cta_text, cf, SAFE_W - 40)
        cy_base = HEIGHT // 2 + 60
        for i, line in enumerate(cta_lines):
            draw.text((cx, cy_base + i * 40), line, font=cf,
                      fill=(255, 230, 100, 200), anchor="mm")

    # TRUE / FALSE buttons (appear after frame 22)
    if frame_idx > 22:
        _draw_tf_buttons(draw, revealed=False, correct_is_true=None)

    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def draw_answer_phase(img: Image.Image, correct_answer: str, explanation: str,
                      reveal_frame: int) -> Image.Image:
    """Highlight the correct button in phosphor green; dim the wrong one."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx = WIDTH // 2

    correct_is_true = correct_answer.strip().upper() in ("TRUE", "YES", "CORRECT")
    _draw_tf_buttons(draw, revealed=True, correct_is_true=correct_is_true)

    # CORRECT! banner above buttons
    bf = _best_font(52)
    by1, by2 = BTN_Y1 - 100, BTN_Y1 - 30
    draw.rounded_rectangle([cx - 195, by1, cx + 195, by2], radius=26,
                            fill=(57, 255, 20, 220))
    draw.text((cx, (by1 + by2) // 2), "✓  CORRECT!", font=bf,
              fill=(0, 0, 0, 255), anchor="mm")

    # Explanation
    if explanation and reveal_frame > 15:
        ef = _best_font(30)
        from video.text_animator import wrap_text
        lines = wrap_text(explanation, ef, SAFE_W - 40)
        for i, line in enumerate(lines):
            draw.text((cx, BTN_Y2 + 40 + i * 40), line, font=ef,
                      fill=(200, 200, 200, 200), anchor="mm")

    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def _draw_tf_buttons(draw: ImageDraw.Draw, revealed: bool,
                     correct_is_true: bool | None) -> None:
    cx = WIDTH // 2

    true_fill  = TRUE_COLOR
    false_fill = FALSE_COLOR

    if revealed and correct_is_true is not None:
        true_fill  = CORRECT_GLOW if correct_is_true  else WRONG_DIM
        false_fill = CORRECT_GLOW if not correct_is_true else WRONG_DIM

        # Glow ring on correct button
        glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        if correct_is_true:
            gd.rounded_rectangle([SAFE_LEFT - 8, BTN_Y1 - 8, cx - BTN_GAP // 2 + 8, BTN_Y2 + 8],
                                  radius=BTN_RADIUS + 4, fill=(57, 255, 20, 60))
        else:
            gd.rounded_rectangle([cx + BTN_GAP // 2 - 8, BTN_Y1 - 8, SAFE_RIGHT + 8, BTN_Y2 + 8],
                                  radius=BTN_RADIUS + 4, fill=(57, 255, 20, 60))

    bf = _best_font(54)

    # TRUE button (left half)
    draw.rounded_rectangle([SAFE_LEFT, BTN_Y1, cx - BTN_GAP // 2, BTN_Y2],
                            radius=BTN_RADIUS, fill=true_fill)
    draw.text(((SAFE_LEFT + cx - BTN_GAP // 2) // 2, (BTN_Y1 + BTN_Y2) // 2),
              "TRUE", font=bf, fill=LABEL_WHITE, anchor="mm")

    # FALSE button (right half)
    draw.rounded_rectangle([cx + BTN_GAP // 2, BTN_Y1, SAFE_RIGHT, BTN_Y2],
                            radius=BTN_RADIUS, fill=false_fill)
    draw.text(((cx + BTN_GAP // 2 + SAFE_RIGHT) // 2, (BTN_Y1 + BTN_Y2) // 2),
              "FALSE", font=bf, fill=LABEL_WHITE, anchor="mm")
