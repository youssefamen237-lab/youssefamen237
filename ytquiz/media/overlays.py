from __future__ import annotations

import random
import textwrap
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ytquiz.utils import ensure_dir, safe_slug


@dataclass(frozen=True)
class OverlayPaths:
    question_png: Path
    hint_png: Path | None
    answer_png: Path


def make_short_overlays(
    *,
    out_dir: Path,
    font_file: Path,
    question: str,
    answer: str,
    options: list[str] | None,
    correct_index: int | None,
    template_id: int,
    rng: random.Random,
    hint_text: str | None,
) -> OverlayPaths:
    return _make_overlays(
        out_dir=out_dir,
        font_file=font_file,
        size=(1080, 1920),
        question=question,
        answer=answer,
        options=options,
        correct_index=correct_index,
        template_id=template_id,
        rng=rng,
        hint_text=hint_text,
        prefix="short",
    )


def make_long_overlays(
    *,
    out_dir: Path,
    font_file: Path,
    question: str,
    answer: str,
    options: list[str] | None,
    correct_index: int | None,
    template_id: int,
    rng: random.Random,
    hint_text: str | None,
    qnum: int,
    qtotal: int,
) -> OverlayPaths:
    q = f"Q{qnum}/{qtotal}: {question}"
    return _make_overlays(
        out_dir=out_dir,
        font_file=font_file,
        size=(1920, 1080),
        question=q,
        answer=answer,
        options=options,
        correct_index=correct_index,
        template_id=template_id,
        rng=rng,
        hint_text=hint_text,
        prefix="long",
    )


def _make_overlays(
    *,
    out_dir: Path,
    font_file: Path,
    size: tuple[int, int],
    question: str,
    answer: str,
    options: list[str] | None,
    correct_index: int | None,
    template_id: int,
    rng: random.Random,
    hint_text: str | None,
    prefix: str,
) -> OverlayPaths:
    ensure_dir(out_dir)
    w, h = size
    base = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    slug = safe_slug(question)[:24]
    q_path = out_dir / f"{prefix}_q_{slug}.png"
    a_path = out_dir / f"{prefix}_a_{slug}.png"
    hint_path = out_dir / f"{prefix}_h_{slug}.png"

    q_img = base.copy()
    _draw_question_block(q_img, font_file, question, options, template_id, rng)
    q_img.save(q_path, format="PNG")

    hint_png: Path | None = None
    if template_id == 4 and hint_text:
        h_img = base.copy()
        _draw_hint_block(h_img, font_file, hint_text, rng)
        h_img.save(hint_path, format="PNG")
        hint_png = hint_path

    a_img = base.copy()
    _draw_answer_block(a_img, font_file, answer, options, correct_index, template_id, rng)
    a_img.save(a_path, format="PNG")

    return OverlayPaths(question_png=q_path, hint_png=hint_png, answer_png=a_path)


def _draw_question_block(img: Image.Image, font_file: Path, question: str, options: list[str] | None, template_id: int, rng: random.Random) -> None:
    w, h = img.size
    draw = ImageDraw.Draw(img)

    q_font = ImageFont.truetype(str(font_file), int(min(w, h) * 0.060))
    opt_font = ImageFont.truetype(str(font_file), int(min(w, h) * 0.048))

    box_w = int(w * 0.88)
    x0 = (w - box_w) // 2
    y0 = int(h * 0.22)
    y1 = int(h * 0.76)

    rect = Image.new("RGBA", (box_w, y1 - y0), (0, 0, 0, 140))
    img.alpha_composite(rect, (x0, y0))

    q_lines = _wrap(draw, question, q_font, box_w - 80)
    q_text = "\n".join(q_lines)

    bbox = draw.multiline_textbbox((0, 0), q_text, font=q_font, spacing=10, align="center")
    tw, th = bbox[2:4]
    qx = x0 + (box_w - tw) // 2
    qy = y0 + 40
    draw.multiline_text(
        (qx, qy),
        q_text,
        font=q_font,
        fill=(255, 255, 255, 255),
        spacing=10,
        align="center",
        stroke_width=4,
        stroke_fill=(0, 0, 0, 255),
    )

    if template_id == 2 and options:
        letters = ["A", "B", "C"]
        opts = options[:3]
        oy = qy + th + 40
        for i, opt in enumerate(opts):
            label = f"{letters[i]}) {opt}"
            lines = _wrap(draw, label, opt_font, box_w - 120)
            t = "\n".join(lines)
            draw.multiline_text(
                (x0 + 60, oy),
                t,
                font=opt_font,
                fill=(255, 255, 255, 255),
                spacing=8,
                align="left",
                stroke_width=3,
                stroke_fill=(0, 0, 0, 255),
            )
            oy += int(opt_font.size * (len(lines) + 1.2))

    if template_id == 5:
        tag = rng.choice(["SPEED ROUND", "QUICK QUIZ", "LIGHTNING"])
        tag_font = ImageFont.truetype(str(font_file), int(min(w, h) * 0.040))
        draw.text(
            (x0 + 50, y0 - 60),
            tag,
            font=tag_font,
            fill=(255, 255, 255, 255),
            stroke_width=3,
            stroke_fill=(0, 0, 0, 255),
        )


def _draw_hint_block(img: Image.Image, font_file: Path, hint: str, rng: random.Random) -> None:
    w, h = img.size
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(font_file), int(min(w, h) * 0.050))

    box_w = int(w * 0.82)
    x0 = (w - box_w) // 2
    y0 = int(h * 0.66)
    y1 = int(h * 0.78)

    rect = Image.new("RGBA", (box_w, y1 - y0), (0, 0, 0, 160))
    img.alpha_composite(rect, (x0, y0))

    lines = _wrap(draw, hint, font, box_w - 70)
    t = "\n".join(lines)
    bbox = draw.multiline_textbbox((0, 0), t, font=font, spacing=8, align="center")
    tw, th = bbox[2:4]
    draw.multiline_text(
        (x0 + (box_w - tw) // 2, y0 + (y1 - y0 - th) // 2),
        t,
        font=font,
        fill=(255, 255, 255, 255),
        spacing=8,
        align="center",
        stroke_width=3,
        stroke_fill=(0, 0, 0, 255),
    )


def _draw_answer_block(
    img: Image.Image,
    font_file: Path,
    answer: str,
    options: list[str] | None,
    correct_index: int | None,
    template_id: int,
    rng: random.Random,
) -> None:
    w, h = img.size
    draw = ImageDraw.Draw(img)

    a_font = ImageFont.truetype(str(font_file), int(min(w, h) * 0.075))
    small = ImageFont.truetype(str(font_file), int(min(w, h) * 0.050))

    box_w = int(w * 0.88)
    x0 = (w - box_w) // 2
    y0 = int(h * 0.30)
    y1 = int(h * 0.70)

    rect = Image.new("RGBA", (box_w, y1 - y0), (0, 0, 0, 160))
    img.alpha_composite(rect, (x0, y0))

    headline = rng.choice(["ANSWER", "CORRECT ANSWER", "THE ANSWER"])
    draw.text(
        (x0 + 60, y0 + 40),
        headline,
        font=small,
        fill=(255, 255, 255, 255),
        stroke_width=3,
        stroke_fill=(0, 0, 0, 255),
    )

    if template_id == 2 and options and correct_index is not None and len(options) >= 2:
        letters = ["A", "B", "C"]
        correct_letter = letters[correct_index] if correct_index < len(letters) else "A"
        answer_line = f"{correct_letter}) {answer}"
    else:
        answer_line = str(answer)

    lines = _wrap(draw, answer_line, a_font, box_w - 120)
    t = "\n".join(lines)
    bbox = draw.multiline_textbbox((0, 0), t, font=a_font, spacing=12, align="center")
    tw, th = bbox[2:4]
    draw.multiline_text(
        (x0 + (box_w - tw) // 2, y0 + (y1 - y0 - th) // 2),
        t,
        font=a_font,
        fill=(255, 255, 255, 255),
        spacing=12,
        align="center",
        stroke_width=5,
        stroke_fill=(0, 0, 0, 255),
    )


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = str(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    cur: list[str] = []
    for w in words:
        test = " ".join(cur + [w])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] <= max_width or not cur:
            cur.append(w)
            continue
        lines.append(" ".join(cur))
        cur = [w]
    if cur:
        lines.append(" ".join(cur))
    if len(lines) > 6:
        lines = lines[:6]
        lines[-1] = textwrap.shorten(lines[-1], width=48, placeholder="...")
    return lines
