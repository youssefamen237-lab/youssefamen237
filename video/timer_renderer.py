"""
video/timer_renderer.py – Quizzaro Circular Timer Renderer
============================================================
Draws the 5-second countdown arc programmatically onto a PIL Image.

Features:
  - Sweeping arc from 12 o'clock, clockwise, shrinking as time passes
  - Color interpolation: solid green (0s elapsed) → amber → solid red (5s elapsed)
  - Background ring in dark grey for contrast
  - Large digit countdown in the centre (5 → 4 → 3 → 2 → 1)
  - Optional glow ring (extra blurred arc drawn first for depth)

All drawing uses PIL primitives — no image assets required.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Timer visual constants
TIMER_RADIUS = 110
TIMER_THICKNESS = 18
GLOW_EXTRA = 8          # extra thickness for the blur pass
DIGIT_FONT_RATIO = 0.85  # digit size relative to radius

COLOR_FULL = (0, 230, 64)    # green at t=0
COLOR_MID = (255, 200, 0)    # amber at t=0.5
COLOR_EMPTY = (255, 45, 45)  # red at t=1.0
COLOR_RING_BG = (55, 55, 55, 180)


def _lerp_color(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def timer_color(progress: float) -> tuple:
    """
    progress: 0.0 (just started, full circle) → 1.0 (finished, empty).
    Returns RGB tuple interpolated green → amber → red.
    """
    if progress < 0.5:
        return _lerp_color(COLOR_FULL, COLOR_MID, progress / 0.5)
    return _lerp_color(COLOR_MID, COLOR_EMPTY, (progress - 0.5) / 0.5)


def draw_timer(
    img: Image.Image,
    progress: float,
    center: tuple[int, int],
    font_path: str | None = None,
    radius: int = TIMER_RADIUS,
    thickness: int = TIMER_THICKNESS,
) -> Image.Image:
    """
    Draw the circular countdown onto *img* (in-place, returns img).

    Args:
        img:       PIL Image (RGB or RGBA) to draw onto.
        progress:  0.0 = full circle (green), 1.0 = empty (red).
        center:    (cx, cy) pixel position of timer centre.
        font_path: Path to .ttf for the digit. Falls back to PIL default.
        radius:    Outer radius of the arc in pixels.
        thickness: Stroke width of the arc in pixels.
    """
    cx, cy = center
    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]

    # ── Glow pass (blurred, wider arc drawn on separate layer) ────────────
    glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    color = timer_color(progress)
    remaining_angle = 360.0 * (1.0 - progress)
    end_angle = -90.0 + remaining_angle

    glow_bbox = [
        cx - radius - GLOW_EXTRA,
        cy - radius - GLOW_EXTRA,
        cx + radius + GLOW_EXTRA,
        cy + radius + GLOW_EXTRA,
    ]
    if remaining_angle > 1.0:
        gd.arc(glow_bbox, start=-90, end=end_angle,
               fill=color + (120,), width=thickness + GLOW_EXTRA * 2)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=10))

    base = img.convert("RGBA")
    base = Image.alpha_composite(base, glow_layer)
    img = base.convert("RGB")

    # ── Background ring ────────────────────────────────────────────────────
    ring_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring_layer)
    rd.arc(bbox, start=0, end=360, fill=COLOR_RING_BG, width=thickness)
    img = Image.alpha_composite(img.convert("RGBA"), ring_layer).convert("RGB")

    # ── Foreground arc ─────────────────────────────────────────────────────
    arc_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ad = ImageDraw.Draw(arc_layer)
    if remaining_angle > 0.5:
        ad.arc(bbox, start=-90, end=end_angle, fill=color + (255,), width=thickness)
    img = Image.alpha_composite(img.convert("RGBA"), arc_layer).convert("RGB")

    # ── Centre digit ───────────────────────────────────────────────────────
    seconds_left = max(0, math.ceil(5.0 * (1.0 - progress)))
    digit_size = int(radius * DIGIT_FONT_RATIO)
    try:
        font = ImageFont.truetype(font_path, digit_size) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    digit_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dd = ImageDraw.Draw(digit_layer)

    # Stroke
    stroke = 4
    for dx in range(-stroke, stroke + 1):
        for dy in range(-stroke, stroke + 1):
            if dx != 0 or dy != 0:
                dd.text((cx + dx, cy + dy), str(seconds_left), font=font,
                        fill=(0, 0, 0, 255), anchor="mm")
    dd.text((cx, cy), str(seconds_left), font=font, fill=(255, 255, 255, 255), anchor="mm")

    img = Image.alpha_composite(img.convert("RGBA"), digit_layer).convert("RGB")
    return img
