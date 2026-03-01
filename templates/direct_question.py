"""
templates/direct_question.py – Quizzaro Direct Question Template
================================================================
Straightforward Q&A format with no options shown — the viewer must
type the answer in the comments before the timer runs out.

Layout:
  ┌─────────────────────────────┐
  │  [QUICK QUESTION badge]     │
  │                             │
  │   Question text (pop-up)    │
  │                             │
  │   CTA text (animated)       │
  │                             │
  │   ❓ icon + countdown hint  │
  └─────────────────────────────┘

Answer phase: phosphor-green answer text + explanation.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH, HEIGHT = 1080, 1920
SAFE_LEFT = int(WIDTH * 0.08)
SAFE_RIGHT = int(WIDTH * 0.92)
SAFE_TOP   = int(HEIGHT * 0.12)
SAFE_W     = SAFE_RIGHT - SAFE_LEFT
PHOSPHOR   = (57, 255, 20, 255)
BADGE_COLOR = (0, 160, 220, 220)


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

    # Badge
    bf = _best_font(38)
    draw.rounded_rectangle([cx - 170, SAFE_TOP + 20, cx + 170, SAFE_TOP + 72],
                            radius=24, fill=BADGE_COLOR)
    draw.text((cx, SAFE_TOP + 46), "QUICK QUESTION", font=bf,
              fill=(255, 255, 255, 255), anchor="mm")

    # Animated question
    q_size = max(12, int(72 * popup_scale))
    qf     = _best_font(q_size)
    lines  = wrap_text(question_text, qf, SAFE_W - 20)
    total_h = len(lines) * (q_size + 14)
    start_y = HEIGHT // 2 - 130 - total_h // 2
    _multiline(draw, lines, cx, start_y, qf,
               fill=(255, 255, 255, popup_alpha), stroke=5)

    # CTA
    if frame_idx > 18:
        cf = _best_font(30)
        cta_lines = wrap_text(cta_text, cf, SAFE_W - 40)
        _multiline(draw, cta_lines, cx, HEIGHT // 2 + 60, cf,
                   fill=(255, 220, 80, 200), stroke=3)

    # Hint icon
    if frame_idx > 25:
        hf = _best_font(44)
        draw.text((cx, int(HEIGHT * 0.72)), "❓ Type your answer below!",
                  font=hf, fill=(200, 200, 255, 160), anchor="mm")

    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def draw_answer_phase(img: Image.Image, correct_answer: str, explanation: str,
                      reveal_frame: int) -> Image.Image:
    from video.text_animator import wrap_text

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)
    cx    = WIDTH // 2

    # Glow answer
    af = _best_font(74 if len(correct_answer) < 16 else 56)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd   = ImageDraw.Draw(glow)
    lines = wrap_text(correct_answer, af, SAFE_W - 30)
    _multiline(gd, lines, cx, HEIGHT // 2 - 60, af, PHOSPHOR, stroke=0)
    from PIL import ImageFilter
    glow = glow.filter(ImageFilter.GaussianBlur(radius=18))

    sharp = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd    = ImageDraw.Draw(sharp)
    _multiline(sd, lines, cx, HEIGHT // 2 - 60, af, PHOSPHOR, stroke=6)

    base = Image.alpha_composite(img.convert("RGBA"), glow)
    base = Image.alpha_composite(base, sharp).convert("RGB")

    # CORRECT banner
    layer2 = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d2     = ImageDraw.Draw(layer2)
    bf     = _best_font(52)
    by1, by2 = HEIGHT // 2 - 220, HEIGHT // 2 - 148
    d2.rounded_rectangle([cx - 195, by1, cx + 195, by2], radius=26,
                          fill=(57, 255, 20, 220))
    d2.text((cx, (by1 + by2) // 2), "✓  CORRECT!", font=bf,
            fill=(0, 0, 0, 255), anchor="mm")

    if explanation and reveal_frame > 15:
        ef    = _best_font(30)
        elines = wrap_text(explanation, ef, SAFE_W - 40)
        for i, line in enumerate(elines[:2]):
            d2.text((cx, HEIGHT // 2 + 100 + i * 40), line, font=ef,
                    fill=(190, 190, 190, 200), anchor="mm")

    return Image.alpha_composite(base.convert("RGBA"), layer2).convert("RGB")
