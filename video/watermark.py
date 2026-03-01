"""
video/watermark.py – Quizzaro Moving Watermark Engine
======================================================
Renders the @Quizzaro_1 channel handle onto every video frame.

Behaviour:
  - 30% opacity (alpha = 77/255)
  - Moves slowly left → right horizontally over the full video duration
  - Vertical position follows a gentle sine wave to feel organic
  - Stays within the top 10% of screen (unobtrusive but visible)
  - Uses the same Montserrat font as the rest of the UI (falls back to PIL default)
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1080
HEIGHT = 1920
SAFE_LEFT = int(WIDTH * 0.08)
SAFE_RIGHT = int(WIDTH * 0.92)
WATERMARK_ALPHA = 77        # 30% of 255
FONT_SIZE = 30
VERTICAL_BAND = 0.06        # occupies top 6% → 12% of screen height


class WatermarkEngine:

    def __init__(self, channel_handle: str = "@Quizzaro_1", font_path: str | None = None) -> None:
        self._handle = channel_handle
        self._font_path = font_path
        self._font = self._load_font()

    def _load_font(self) -> ImageFont.FreeTypeFont:
        if self._font_path:
            try:
                return ImageFont.truetype(self._font_path, FONT_SIZE)
            except Exception:
                pass
        # Try the cached Montserrat font from data/fonts/
        for candidate in [
            "data/fonts/montserrat_regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]:
            try:
                return ImageFont.truetype(candidate, FONT_SIZE)
            except Exception:
                continue
        return ImageFont.load_default()

    def _measure_text(self) -> tuple[int, int]:
        dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        bbox = dummy.textbbox((0, 0), self._handle, font=self._font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def apply(self, img: Image.Image, frame_index: int, total_frames: int) -> Image.Image:
        """
        Composite the watermark onto *img* and return the result.
        frame_index and total_frames determine the position.
        """
        t = frame_index / max(total_frames - 1, 1)   # 0.0 → 1.0

        text_w, text_h = self._measure_text()

        # Horizontal: drift from SAFE_LEFT to (SAFE_RIGHT - text_w)
        x = int(SAFE_LEFT + t * (SAFE_RIGHT - SAFE_LEFT - text_w - 10))
        x = max(SAFE_LEFT, min(x, SAFE_RIGHT - text_w - 10))

        # Vertical: sine wave within top band [6% H … 12% H]
        base_y = int(HEIGHT * 0.06)
        wave_amplitude = int(HEIGHT * VERTICAL_BAND * 0.5)
        y = int(base_y + wave_amplitude * math.sin(t * math.pi * 2))
        y = max(int(HEIGHT * 0.04), min(y, int(HEIGHT * 0.13)))

        # Render on RGBA layer then composite
        wm_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(wm_layer)

        # Subtle shadow for readability on any background
        shadow_color = (0, 0, 0, 60)
        draw.text((x + 2, y + 2), self._handle, font=self._font, fill=shadow_color)

        # Main text at 30% alpha
        draw.text((x, y), self._handle, font=self._font,
                  fill=(255, 255, 255, WATERMARK_ALPHA))

        result = Image.alpha_composite(img.convert("RGBA"), wm_layer)
        return result.convert("RGB")
