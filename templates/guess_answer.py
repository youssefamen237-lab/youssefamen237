"""
templates/guess_answer.py – Quizzaro Guess the Answer Template
==============================================================
Shows the question with the key answer word replaced by "_ _ _ _" blanks,
creating a fill-in-the-blank feel. Blanks are revealed letter-by-letter
during the answer phase using a typewriter effect.

Layout question phase:
  ┌─────────────────────────────┐
  │  [GUESS THE ANSWER badge]   │
  │   Question with _ _ _ _     │
  │   CTA                       │
  │   [  _ _ _ _  ] hint box    │
  └─────────────────────────────┘
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH, HEIGHT = 1080, 1920
SAFE_LEFT  = int(WIDTH * 0.08)
SAFE_RIGHT = int(WIDTH * 0.92)
SAFE_TOP   = int(HEIGHT * 0.12)
SAFE_W     = SAFE_RIGHT - SAFE_LEFT
PHOSPHOR   = (57, 255, 20, 255)
BADGE_COLOR = (220, 100, 0, 230)


def _best_font(size):
    for p in ["data/fonts/montserrat_extrabold.ttf",
              "data/fonts/montserrat_bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _blank_answer(answer: str) -> str:
    """Replace letters with underscores, keep spaces."""
    return " ".join("_ " * len(word) for word in answer.split())


def _typewriter_reveal(answer: str, reveal_frame: int) -> str:
    """Reveal one character per 3 frames."""
    chars_visible = min(len(answer), reveal_frame // 3 + 1)
    visible   = answer[:chars_visible]
    remaining = "_ " * max(0, len(answer) - chars_visible)
    return visible + remaining.rstrip()


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
                        correct_answer: str, frame_idx: int,
                        popup_scale: float, popup_alpha: int) -> Image.Image:
    from video.text_animator import wrap_text

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)
    cx    = WIDTH // 2

    # Badge
    bf = _best_font(36)
    draw.rounded_rectangle([cx - 195, SAFE_TOP + 20, cx + 195, SAFE_TOP + 72],
                            radius=24, fill=BADGE_COLOR)
    draw.text((cx, SAFE_TOP + 46), "GUESS THE ANSWER", font=bf,
              fill=(255, 255, 255, 255), anchor="mm")

    # Question
    q_size = max(12, int(66 * popup_scale))
    qf     = _best_font(q_size)
    lines  = wrap_text(question_text, qf, SAFE_W - 20)
    total_h = len(lines) * (q_size + 14)
    start_y = HEIGHT // 2 - 140 - total_h // 2
    _multiline(draw, lines, cx, start_y, qf,
               fill=(255, 255, 255, popup_alpha), stroke=5)

    # Blank hint box
    blank_text = _blank_answer(correct_answer)
    bl_f = _best_font(52)
    box_y1, box_y2 = HEIGHT // 2 + 60, HEIGHT // 2 + 140
    draw.rounded_rectangle([SAFE_LEFT + 20, box_y1, SAFE_RIGHT - 20, box_y2],
                            radius=18, fill=(255, 255, 255, 25),
                            outline=(255, 255, 255, 80), width=2)
    draw.text((cx, (box_y1 + box_y2) // 2), blank_text[:24], font=bl_f,
              fill=(180, 220, 255, 220), anchor="mm")

    # CTA
    if frame_idx > 18:
        cf = _best_font(28)
        for i, line in enumerate(wrap_text(cta_text, cf, SAFE_W - 40)):
            draw.text((cx, HEIGHT // 2 + 165 + i * 36), line, font=cf,
                      fill=(255, 220, 80, 190), anchor="mm")

    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def draw_answer_phase(img: Image.Image, correct_answer: str, explanation: str,
                      reveal_frame: int) -> Image.Image:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)
    cx    = WIDTH // 2

    # Typewriter reveal
    revealed_text = _typewriter_reveal(correct_answer, reveal_frame)
    af   = _best_font(68)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd   = ImageDraw.Draw(glow)
    gd.text((cx, HEIGHT // 2 + 100), revealed_text, font=af,
            fill=PHOSPHOR, anchor="mm")
    from PIL import ImageFilter
    glow = glow.filter(ImageFilter.GaussianBlur(radius=16))

    sharp = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd    = ImageDraw.Draw(sharp)
    sd.text((cx, HEIGHT // 2 + 100), correct_answer, font=af,
            fill=PHOSPHOR, anchor="mm")

    base = Image.alpha_composite(img.convert("RGBA"), glow)
    base = Image.alpha_composite(base, sharp).convert("RGB")

    layer2 = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d2     = ImageDraw.Draw(layer2)
    bf     = _best_font(50)
    by1 = HEIGHT // 2 - 200
    d2.rounded_rectangle([cx - 190, by1, cx + 190, by1 + 72],
                          radius=26, fill=(57, 255, 20, 220))
    d2.text((cx, by1 + 36), "✓  CORRECT!", font=bf,
            fill=(0, 0, 0, 255), anchor="mm")

    if explanation and reveal_frame > 12:
        from video.text_animator import wrap_text
        ef = _best_font(28)
        for i, line in enumerate(wrap_text(explanation, ef, SAFE_W - 40)[:2]):
            d2.text((cx, HEIGHT // 2 + 180 + i * 38), line, font=ef,
                    fill=(190, 190, 190, 200), anchor="mm")

    return Image.alpha_composite(base.convert("RGBA"), layer2).convert("RGB")
