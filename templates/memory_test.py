"""
templates/memory_test.py – Quizzaro Memory Test Template
=========================================================
Shows a fact/statement for 2 seconds (memorise phase), then blanks it
and asks a question about it. Forces active engagement.

Unique visual hooks:
  - "MEMORISE THIS!" phase with yellow highlight bar over key text
  - Text is shown then hidden with a "swipe-up" wipe effect
  - 🔁 MEMORY TEST badge with cyan palette
  - Answer phase shows original fact + correct answer side by side
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH, HEIGHT = 1080, 1920
SAFE_LEFT  = int(WIDTH * 0.08)
SAFE_RIGHT = int(WIDTH * 0.92)
SAFE_TOP   = int(HEIGHT * 0.12)
SAFE_W     = SAFE_RIGHT - SAFE_LEFT
PHOSPHOR   = (57, 255, 20, 255)
BADGE_COLOR = (0, 190, 200, 230)
HIGHLIGHT   = (255, 230, 0, 80)


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
                        fun_fact: str, frame_idx: int,
                        popup_scale: float, popup_alpha: int) -> Image.Image:
    from video.text_animator import wrap_text

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)
    cx    = WIDTH // 2

    # Badge
    bf = _best_font(38)
    draw.rounded_rectangle([cx - 195, SAFE_TOP + 18, cx + 195, SAFE_TOP + 74],
                            radius=24, fill=BADGE_COLOR)
    draw.text((cx, SAFE_TOP + 46), "🔁 MEMORY TEST", font=bf,
              fill=(255, 255, 255, 255), anchor="mm")

    # "MEMORISE THIS!" label (first 40 frames)
    if frame_idx < 40 and fun_fact:
        mf = _best_font(34)
        draw.text((cx, SAFE_TOP + 100), "MEMORISE THIS:", font=mf,
                  fill=(255, 230, 0, 220), anchor="mm")
        ff_lines = wrap_text(fun_fact[:120], _best_font(38), SAFE_W - 30)
        fact_y = SAFE_TOP + 148
        for i, line in enumerate(ff_lines[:3]):
            fy = fact_y + i * 50
            # Highlight bar
            draw.rectangle([SAFE_LEFT, fy - 22, SAFE_RIGHT, fy + 24], fill=HIGHLIGHT)
            _multiline(draw, [line], cx, fy, _best_font(38),
                       fill=(255, 255, 255, 230), spacing=0, stroke=4)

    # Question (animated, appears after frame 20)
    if frame_idx > 20:
        q_size = max(12, int(64 * popup_scale))
        qf     = _best_font(q_size)
        lines  = wrap_text(question_text, qf, SAFE_W - 20)
        total_h = len(lines) * (q_size + 14)
        start_y = HEIGHT // 2 - 60 - total_h // 2
        _multiline(draw, lines, cx, start_y, qf,
                   fill=(255, 255, 255, popup_alpha), stroke=5)

    # CTA
    if frame_idx > 30:
        cf = _best_font(28)
        for i, line in enumerate(wrap_text(cta_text, cf, SAFE_W - 40)):
            draw.text((cx, HEIGHT // 2 + 100 + i * 36), line, font=cf,
                      fill=(100, 240, 255, 190), anchor="mm")

    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def draw_answer_phase(img: Image.Image, correct_answer: str, explanation: str,
                      reveal_frame: int) -> Image.Image:
    from video.text_animator import wrap_text
    from PIL import ImageFilter

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)
    cx    = WIDTH // 2

    af   = _best_font(70 if len(correct_answer) < 18 else 52)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd   = ImageDraw.Draw(glow)
    lines = wrap_text(correct_answer, af, SAFE_W - 30)
    _multiline(gd, lines, cx, HEIGHT // 2 + 50, af, PHOSPHOR, stroke=0)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=18))

    sharp = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd    = ImageDraw.Draw(sharp)
    _multiline(sd, lines, cx, HEIGHT // 2 + 50, af, PHOSPHOR, stroke=6)

    base = Image.alpha_composite(img.convert("RGBA"), glow)
    base = Image.alpha_composite(base, sharp).convert("RGB")

    l2 = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d2 = ImageDraw.Draw(l2)
    bf = _best_font(46)
    by1 = HEIGHT // 2 - 210
    d2.rounded_rectangle([cx - 210, by1, cx + 210, by1 + 74],
                          radius=26, fill=(0, 190, 200, 230))
    d2.text((cx, by1 + 37), "🔁 MEMORY UNLOCKED ✓", font=bf,
            fill=(255, 255, 255, 255), anchor="mm")

    if explanation and reveal_frame > 12:
        ef = _best_font(28)
        for i, line in enumerate(wrap_text(explanation, ef, SAFE_W - 40)[:2]):
            d2.text((cx, HEIGHT // 2 + 190 + i * 38), line, font=ef,
                    fill=(190, 190, 190, 200), anchor="mm")

    return Image.alpha_composite(base.convert("RGBA"), l2).convert("RGB")
