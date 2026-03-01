"""
templates/multiple_choice.py – Quizzaro Multiple Choice Template
=================================================================
Renders 4 answer options (A / B / C / D) as pill buttons below the question.

Layout:
  ┌─────────────────────────────┐
  │  [MULTIPLE CHOICE badge]    │
  │   Question text (pop-up)    │
  │   CTA text                  │
  │  [A] Option text            │
  │  [B] Option text            │
  │  [C] Option text            │
  │  [D] Option text            │
  └─────────────────────────────┘

During answer phase the correct option button glows phosphor green;
wrong options fade to dark.
Options are shuffled on every call (correct answer randomised in position).
"""

from __future__ import annotations

import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH, HEIGHT = 1080, 1920
SAFE_LEFT = int(WIDTH * 0.08)
SAFE_RIGHT = int(WIDTH * 0.92)
SAFE_TOP   = int(HEIGHT * 0.12)
SAFE_W     = SAFE_RIGHT - SAFE_LEFT

OPTION_START_Y  = int(HEIGHT * 0.58)
OPTION_HEIGHT   = 84
OPTION_SPACING  = 14
OPTION_RADIUS   = 18

BADGE_COLOR    = (80, 40, 220, 220)
OPTION_NORMAL  = (255, 255, 255, 35)
OPTION_CORRECT = (57, 255, 20, 230)
OPTION_WRONG   = (50, 50, 50, 150)
LABEL_COLORS   = [(255, 100, 100, 255), (100, 200, 255, 255),
                  (255, 210, 60, 255),  (160, 255, 120, 255)]


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


def _build_options(correct_answer: str, wrong_answers: list[str]) -> list[tuple[str, str, bool]]:
    """Return list of (label, text, is_correct) shuffled."""
    labels = ["A", "B", "C", "D"]
    options = [(correct_answer, True)] + [(w, False) for w in wrong_answers[:3]]
    random.shuffle(options)
    return [(labels[i], opt[0], opt[1]) for i, opt in enumerate(options)]


def draw_question_phase(img: Image.Image, question_text: str, cta_text: str,
                        correct_answer: str, wrong_answers: list[str],
                        frame_idx: int, popup_scale: float, popup_alpha: int) -> Image.Image:
    from video.text_animator import wrap_text

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)
    cx    = WIDTH // 2

    # Badge
    bf = _best_font(36)
    draw.rounded_rectangle([cx - 185, SAFE_TOP + 20, cx + 185, SAFE_TOP + 72],
                            radius=24, fill=BADGE_COLOR)
    draw.text((cx, SAFE_TOP + 46), "MULTIPLE CHOICE", font=bf,
              fill=(255, 255, 255, 255), anchor="mm")

    # Question text (animated)
    q_size = max(12, int(60 * popup_scale))
    qf     = _best_font(q_size)
    lines  = wrap_text(question_text, qf, SAFE_W - 20)
    line_h = q_size + 12
    total_h = len(lines) * line_h
    start_y = int(HEIGHT * 0.28) - total_h // 2
    for i, line in enumerate(lines):
        y = start_y + i * line_h
        for dx in range(-5, 6):
            for dy in range(-5, 6):
                if dx or dy:
                    draw.text((cx + dx, y + dy), line, font=qf,
                              fill=(0, 0, 0, 255), anchor="mm")
        draw.text((cx, y), line, font=qf,
                  fill=(255, 255, 255, popup_alpha), anchor="mm")

    # CTA
    if frame_idx > 18:
        cf = _best_font(28)
        for i, line in enumerate(wrap_text(cta_text, cf, SAFE_W - 40)):
            draw.text((cx, int(HEIGHT * 0.51) + i * 36), line, font=cf,
                      fill=(255, 220, 80, 200), anchor="mm")

    # Option buttons (after frame 20)
    if frame_idx > 20:
        options = _build_options(correct_answer, wrong_answers)
        _draw_options(draw, options, revealed=False, correct_answer=correct_answer)

    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def draw_answer_phase(img: Image.Image, correct_answer: str, wrong_answers: list[str],
                      explanation: str, reveal_frame: int) -> Image.Image:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)
    cx    = WIDTH // 2

    options = _build_options(correct_answer, wrong_answers)
    _draw_options(draw, options, revealed=True, correct_answer=correct_answer)

    # CORRECT! banner
    bf = _best_font(50)
    by1 = OPTION_START_Y - 110
    by2 = OPTION_START_Y - 40
    draw.rounded_rectangle([cx - 195, by1, cx + 195, by2], radius=26,
                            fill=(57, 255, 20, 220))
    draw.text((cx, (by1 + by2) // 2), "✓  CORRECT!", font=bf,
              fill=(0, 0, 0, 255), anchor="mm")

    # Explanation
    if explanation and reveal_frame > 15:
        ef   = _best_font(28)
        from video.text_animator import wrap_text
        lines = wrap_text(explanation, ef, SAFE_W - 40)
        last_opt_bottom = OPTION_START_Y + 4 * (OPTION_HEIGHT + OPTION_SPACING)
        for i, line in enumerate(lines[:2]):
            draw.text((cx, last_opt_bottom + 30 + i * 36), line, font=ef,
                      fill=(190, 190, 190, 200), anchor="mm")

    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def _draw_options(draw: ImageDraw.Draw, options: list[tuple[str, str, bool]],
                  revealed: bool, correct_answer: str) -> None:
    of = _best_font(34)
    lf = _best_font(38)

    for i, (label, text, is_correct) in enumerate(options):
        y1 = OPTION_START_Y + i * (OPTION_HEIGHT + OPTION_SPACING)
        y2 = y1 + OPTION_HEIGHT

        if revealed:
            fill = OPTION_CORRECT if is_correct else OPTION_WRONG
        else:
            fill = OPTION_NORMAL

        draw.rounded_rectangle([SAFE_LEFT, y1, SAFE_RIGHT, y2],
                                radius=OPTION_RADIUS, fill=fill)

        # Label circle
        lx = SAFE_LEFT + 50
        ly = (y1 + y2) // 2
        lc = LABEL_COLORS[i] if not revealed else (
            (57, 255, 20, 255) if is_correct else (100, 100, 100, 255))
        draw.ellipse([lx - 22, ly - 22, lx + 22, ly + 22], fill=lc)
        draw.text((lx, ly), label, font=lf, fill=(0, 0, 0, 255), anchor="mm")

        # Option text (truncate if too long)
        short_text = text if len(text) < 38 else text[:36] + "…"
        draw.text((SAFE_LEFT + 90, ly), short_text, font=of,
                  fill=(255, 255, 255, 230), anchor="lm")
