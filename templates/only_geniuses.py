"""
templates/only_geniuses.py – Quizzaro "Only Geniuses" Template
==============================================================
Premium ego-bait format. The badge implies the question is hard,
creating high comment engagement from viewers trying to prove themselves.

Unique visual hooks:
  - 🧠 ONLY GENIUSES badge with purple/gold gradient feel
  - "IQ TEST" subtitle
  - Star-rating difficulty indicator (★★★★★) drawn programmatically
  - Answer reveals with "GENIUS LEVEL ✓" badge instead of "CORRECT!"
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH, HEIGHT = 1080, 1920
SAFE_LEFT  = int(WIDTH * 0.08)
SAFE_RIGHT = int(WIDTH * 0.92)
SAFE_TOP   = int(HEIGHT * 0.12)
SAFE_W     = SAFE_RIGHT - SAFE_LEFT
PHOSPHOR   = (57, 255, 20, 255)
BADGE_COLOR = (110, 30, 200, 240)
STAR_COLOR  = (255, 215, 0, 255)


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

    # Badge
    bf = _best_font(38)
    draw.rounded_rectangle([cx - 205, SAFE_TOP + 18, cx + 205, SAFE_TOP + 74],
                            radius=24, fill=BADGE_COLOR)
    draw.text((cx, SAFE_TOP + 46), "🧠 ONLY GENIUSES", font=bf,
              fill=(255, 215, 0, 255), anchor="mm")

    # IQ subtitle
    sf = _best_font(30)
    draw.text((cx, SAFE_TOP + 92), "Can you pass this IQ test?", font=sf,
              fill=(180, 140, 255, 200), anchor="mm")

    # Stars
    if frame_idx > 12:
        star_f = _best_font(38)
        draw.text((cx, SAFE_TOP + 138), "★ ★ ★ ★ ★", font=star_f,
                  fill=STAR_COLOR, anchor="mm")

    # Question
    q_size = max(12, int(68 * popup_scale))
    qf     = _best_font(q_size)
    lines  = wrap_text(question_text, qf, SAFE_W - 20)
    total_h = len(lines) * (q_size + 14)
    start_y = HEIGHT // 2 - 80 - total_h // 2
    _multiline(draw, lines, cx, start_y, qf,
               fill=(255, 255, 255, popup_alpha), stroke=5)

    # CTA
    if frame_idx > 18:
        cf = _best_font(30)
        for i, line in enumerate(wrap_text(cta_text, cf, SAFE_W - 40)):
            draw.text((cx, HEIGHT // 2 + 110 + i * 38), line, font=cf,
                      fill=(200, 160, 255, 200), anchor="mm")

    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def draw_answer_phase(img: Image.Image, correct_answer: str, explanation: str,
                      reveal_frame: int) -> Image.Image:
    from video.text_animator import wrap_text
    from PIL import ImageFilter

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)
    cx    = WIDTH // 2

    af    = _best_font(72 if len(correct_answer) < 16 else 54)
    glow  = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd    = ImageDraw.Draw(glow)
    lines = wrap_text(correct_answer, af, SAFE_W - 30)
    _multiline(gd, lines, cx, HEIGHT // 2 + 60, af, PHOSPHOR, stroke=0)
    glow  = glow.filter(ImageFilter.GaussianBlur(radius=18))
    sharp = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd    = ImageDraw.Draw(sharp)
    _multiline(sd, lines, cx, HEIGHT // 2 + 60, af, PHOSPHOR, stroke=6)

    base = Image.alpha_composite(img.convert("RGBA"), glow)
    base = Image.alpha_composite(base, sharp).convert("RGB")

    l2 = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d2 = ImageDraw.Draw(l2)
    bf = _best_font(44)
    by1 = HEIGHT // 2 - 210
    d2.rounded_rectangle([cx - 230, by1, cx + 230, by1 + 74],
                          radius=26, fill=(110, 30, 200, 230))
    d2.text((cx, by1 + 37), "🧠 GENIUS LEVEL ✓", font=bf,
            fill=(255, 215, 0, 255), anchor="mm")

    if explanation and reveal_frame > 12:
        ef = _best_font(28)
        for i, line in enumerate(wrap_text(explanation, ef, SAFE_W - 40)[:2]):
            d2.text((cx, HEIGHT // 2 + 190 + i * 38), line, font=ef,
                    fill=(190, 190, 190, 200), anchor="mm")

    return Image.alpha_composite(base.convert("RGBA"), l2).convert("RGB")
