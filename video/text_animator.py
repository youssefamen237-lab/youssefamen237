"""
video/text_animator.py – Quizzaro Text Animator
=================================================
Generates per-frame parameters for the pop-up text animation:
  - Cubic ease-out scale: 0 → 1.0 over POPUP_FRAMES frames (≈0.35s at 30fps)
  - Fade-in alpha: 0 → 255 over the same window
  - Returns an AnimFrame dataclass consumed by video_renderer._render_frame()

Also provides helpers for word-wrapping and font-size auto-fitting so
that the question always fits inside the Safe Area regardless of length.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

# Safe area constants (must match video_renderer.py)
SAFE_LEFT = int(1080 * 0.08)
SAFE_RIGHT = int(1080 * 0.92)
SAFE_W = SAFE_RIGHT - SAFE_LEFT

FPS = 30
POPUP_DURATION_SEC = 0.35
POPUP_FRAMES = int(FPS * POPUP_DURATION_SEC)  # 10 frames


@dataclass
class AnimFrame:
    scale: float      # 0.0 → 1.0
    alpha: int        # 0 → 255
    font_size: int    # final rendered font size at full scale


def ease_out_cubic(t: float) -> float:
    """t in [0, 1] → eased value in [0, 1]. Snappy pop-up feel."""
    return 1.0 - (1.0 - t) ** 3


def get_popup_frame(frame_idx: int, full_font_size: int) -> AnimFrame:
    """
    Return AnimFrame for frame_idx inside the popup animation window.
    frame_idx=0 is the first frame of the popup.
    After POPUP_FRAMES, scale and alpha are clamped to 1.0 / 255.
    """
    t = min(frame_idx / POPUP_FRAMES, 1.0)
    scale = ease_out_cubic(t)
    alpha = int(255 * min(1.0, t * 1.8))   # alpha leads scale slightly
    rendered_size = max(12, int(full_font_size * scale))
    return AnimFrame(scale=scale, alpha=alpha, font_size=rendered_size)


def auto_font_size(
    text: str,
    max_width: int,
    max_height: int,
    font_path: str | None,
    size_max: int = 80,
    size_min: int = 34,
) -> int:
    """
    Binary-search for the largest font size where all wrapped lines of
    *text* fit inside max_width × max_height.
    Returns an integer font size.
    """
    lo, hi = size_min, size_max
    while lo < hi - 1:
        mid = (lo + hi) // 2
        try:
            font = ImageFont.truetype(font_path, mid) if font_path else ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()
        lines = wrap_text(text, font, max_width)
        total_h = _measure_block_height(lines, font)
        if total_h <= max_height:
            lo = mid
        else:
            hi = mid
    return lo


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for word in words:
        test = f"{current} {word}".strip()
        w = dummy.textbbox((0, 0), test, font=font)[2]
        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def _measure_block_height(lines: list[str], font: ImageFont.FreeTypeFont, spacing: int = 12) -> int:
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    total = 0
    for line in lines:
        bbox = dummy.textbbox((0, 0), line, font=font)
        total += (bbox[3] - bbox[1]) + spacing
    return total
