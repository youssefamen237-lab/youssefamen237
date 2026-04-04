"""
core/captions.py
================
Generates caption overlay images (PIL/Pillow) for each frame of a Short.

Frame 1 (hook) : Yellow text, Bebas Neue, large font, semi-transparent
                 black band behind the text for legibility on any background.
Frame 2 (body) : White text, Bebas Neue, medium font, split across sentences
                 with one sentence per caption beat.
Frame 3 (cta)  : White text, smaller font, centred near the bottom.

Each public method returns a list of (PIL.Image, duration_secs) tuples
that video_editor.py stamps onto the corresponding video segment.
"""

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from config.settings import (
    BEBAS_NEUE_FONT,
    CAPTION_MAX_CHARS_PER_LINE,
    CAPTION_Y_RATIO,
    COLOR_BODY_TEXT,
    COLOR_CTA_TEXT,
    COLOR_HOOK_BG,
    COLOR_HOOK_TEXT,
    COLOR_TEXT_SHADOW,
    FONT_SIZE_BODY,
    FONT_SIZE_CTA,
    FONT_SIZE_HOOK,
    SHADOW_OFFSET,
    TEXT_STROKE_COLOR,
    TEXT_STROKE_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# Transparent base canvas size
_W: int = VIDEO_WIDTH
_H: int = VIDEO_HEIGHT

# Bottom-of-frame Y anchor for CTA text (90% down)
_CTA_Y_RATIO: float = 0.88

# Band padding above/below text (px)
_BAND_PADDING: int = 28


@dataclass
class CaptionFrame:
    """
    One rendered caption overlay ready to composite onto a video frame.

    Attributes
    ----------
    image        : RGBA PIL Image (same size as video — transparent background).
    duration     : How long this caption should be displayed (seconds).
    text         : The raw text displayed (for debugging / logging).
    frame_type   : 'hook' | 'body' | 'cta'
    """
    image:      Image.Image
    duration:   float
    text:       str
    frame_type: str


# ── Font loader ────────────────────────────────────────────────────────────

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load Bebas Neue at `size` px.  Falls back to Pillow default on error."""
    try:
        return ImageFont.truetype(str(BEBAS_NEUE_FONT), size)
    except (IOError, OSError) as exc:
        logger.warning(
            "Bebas Neue not found (%s). Using Pillow default font.", exc
        )
        return ImageFont.load_default()


# ── Text measurement ────────────────────────────────────────────────────────

def _measure_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
) -> tuple[int, int]:
    """Return (width, height) of rendered text using getbbox."""
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=TEXT_STROKE_WIDTH)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


# ── Text splitter ───────────────────────────────────────────────────────────

def _split_to_lines(text: str, max_chars: int = CAPTION_MAX_CHARS_PER_LINE) -> list[str]:
    """
    Wrap `text` into lines of at most `max_chars` characters.
    Splits on word boundaries; never truncates words.
    """
    return textwrap.wrap(text, width=max_chars, break_long_words=False)


def _split_body_into_beats(body: str) -> list[str]:
    """
    Split body text into 1-3 caption beats (one per sentence or clause).
    Each beat will display for a proportional share of the body frame duration.

    Strategy:
    - Split on '. ', '! ', '? ', ', ' (clause break) in that priority order.
    - If the body is a single short sentence, return it as one beat.
    - Cap at 3 beats maximum.
    """
    import re

    # Try sentence splits first
    sentences = re.split(r'(?<=[.!?])\s+', body.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) >= 2:
        return sentences[:3]

    # Single sentence — try splitting on commas
    clauses = [c.strip() for c in body.split(",") if c.strip()]
    if len(clauses) >= 2:
        return clauses[:3]

    # No natural split — return as one beat
    return [body.strip()]


# ══════════════════════════════════════════════════════════════════════════
# DRAWING PRIMITIVES
# ══════════════════════════════════════════════════════════════════════════

def _draw_text_centred(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    color: tuple,
    y_anchor: int,
    line_spacing: int = 12,
) -> int:
    """
    Draw multi-line centred text with drop-shadow and stroke.
    Returns the total pixel height consumed by the text block.
    """
    line_heights = []
    for line in lines:
        _, h = _measure_text(draw, line, font)
        line_heights.append(h)

    total_height = sum(line_heights) + line_spacing * (len(lines) - 1)
    y = y_anchor - total_height // 2

    for i, line in enumerate(lines):
        w, h = _measure_text(draw, line, font)
        x = (_W - w) // 2

        # Drop shadow
        draw.text(
            (x + SHADOW_OFFSET[0], y + SHADOW_OFFSET[1]),
            line,
            font=font,
            fill=COLOR_TEXT_SHADOW,
        )

        # Stroke (outline)
        draw.text(
            (x, y),
            line,
            font=font,
            fill=color,
            stroke_width=TEXT_STROKE_WIDTH,
            stroke_fill=TEXT_STROKE_COLOR,
        )

        y += h + line_spacing

    return total_height


def _draw_band(
    img: Image.Image,
    y_top: int,
    y_bottom: int,
    color_rgba: tuple = COLOR_HOOK_BG,
) -> None:
    """Draw a semi-transparent horizontal band behind text."""
    band = Image.new("RGBA", (_W, _H), (0, 0, 0, 0))
    band_draw = ImageDraw.Draw(band)
    band_draw.rectangle(
        [(0, y_top - _BAND_PADDING), (_W, y_bottom + _BAND_PADDING)],
        fill=color_rgba,
    )
    img.alpha_composite(band)


# ══════════════════════════════════════════════════════════════════════════
# PUBLIC CAPTION GENERATORS
# ══════════════════════════════════════════════════════════════════════════

class CaptionEngine:
    """
    Renders all caption overlays for one Short.

    Usage
    -----
        engine = CaptionEngine()
        hook_frame  = engine.render_hook(hook_text, duration=1.5)
        body_frames = engine.render_body(body_text, total_duration=5.5)
        cta_frame   = engine.render_cta(cta_text,  duration=1.0)
    """

    def __init__(self) -> None:
        self._font_hook = _load_font(FONT_SIZE_HOOK)
        self._font_body = _load_font(FONT_SIZE_BODY)
        self._font_cta  = _load_font(FONT_SIZE_CTA)

    # ── Hook frame ─────────────────────────────────────────────────────────

    def render_hook(self, text: str, duration: float) -> CaptionFrame:
        """
        Render the yellow hook caption overlay.

        Parameters
        ----------
        text     : Hook sentence.
        duration : Display duration in seconds (= hook audio duration).

        Returns
        -------
        CaptionFrame with a single RGBA image covering the full video canvas.
        """
        img  = Image.new("RGBA", (_W, _H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        lines   = _split_to_lines(text, max_chars=16)   # hook is large — fewer chars/line
        y_anchor = int(_H * CAPTION_Y_RATIO)

        # Measure block height for band
        total_h = sum(_measure_text(draw, l, self._font_hook)[1] for l in lines)
        total_h += 12 * max(0, len(lines) - 1)

        _draw_band(
            img,
            y_top=y_anchor - total_h // 2,
            y_bottom=y_anchor + total_h // 2,
        )

        _draw_text_centred(
            draw=draw,
            lines=lines,
            font=self._font_hook,
            color=COLOR_HOOK_TEXT,
            y_anchor=y_anchor,
        )

        logger.debug("Hook caption rendered: '%s'", text[:60])
        return CaptionFrame(image=img, duration=duration, text=text, frame_type="hook")

    # ── Body frames ────────────────────────────────────────────────────────

    def render_body(self, text: str, total_duration: float) -> list[CaptionFrame]:
        """
        Split body text into beat-level caption frames.

        Each beat gets an equal share of `total_duration`.  Returns a list
        of CaptionFrame objects — one per beat — that video_editor.py
        sequences as consecutive overlays on the body segment.

        Parameters
        ----------
        text           : Body fact text (1-2 sentences).
        total_duration : Full body segment duration in seconds.

        Returns
        -------
        List of CaptionFrame (length 1-3).
        """
        beats         = _split_body_into_beats(text)
        beat_duration = total_duration / len(beats)
        frames: list[CaptionFrame] = []

        for beat in beats:
            img  = Image.new("RGBA", (_W, _H), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            lines    = _split_to_lines(beat, max_chars=CAPTION_MAX_CHARS_PER_LINE)
            y_anchor = int(_H * CAPTION_Y_RATIO)

            _draw_text_centred(
                draw=draw,
                lines=lines,
                font=self._font_body,
                color=COLOR_BODY_TEXT,
                y_anchor=y_anchor,
            )

            frames.append(CaptionFrame(
                image=img,
                duration=beat_duration,
                text=beat,
                frame_type="body",
            ))

        logger.debug(
            "Body captions rendered: %d beat(s) @ %.2fs each",
            len(frames), beat_duration,
        )
        return frames

    # ── CTA frame ──────────────────────────────────────────────────────────

    def render_cta(self, text: str, duration: float) -> CaptionFrame:
        """
        Render the CTA caption overlay (white, smaller font, lower position).

        Parameters
        ----------
        text     : CTA sentence.
        duration : Display duration in seconds.

        Returns
        -------
        CaptionFrame with RGBA image.
        """
        img  = Image.new("RGBA", (_W, _H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        lines    = _split_to_lines(text, max_chars=CAPTION_MAX_CHARS_PER_LINE)
        y_anchor = int(_H * _CTA_Y_RATIO)

        _draw_text_centred(
            draw=draw,
            lines=lines,
            font=self._font_cta,
            color=COLOR_CTA_TEXT,
            y_anchor=y_anchor,
        )

        logger.debug("CTA caption rendered: '%s'", text[:60])
        return CaptionFrame(image=img, duration=duration, text=text, frame_type="cta")
