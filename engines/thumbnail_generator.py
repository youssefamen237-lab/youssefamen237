"""
engines/thumbnail_generator.py
"""
from __future__ import annotations
import json, os, re, subprocess, tempfile
from pathlib import Path
from typing import List, Optional
import structlog
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from cascade.llm.llm_cascade import get_llm
from storage.supabase_client import get_db

logger = structlog.get_logger(__name__)

_W, _H = 1280, 720
_GRADIENT_HEIGHT_RATIO = 0.45
_FALLBACK_BANNED = ["facts about", "did you know", "top 10", "top 5"]

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]

_SYSTEM = (
    "You write short, punchy YouTube thumbnail text for nature/science videos. "
    "Output is 2-4 words, ALL CAPS, designed to create curiosity. "
    "Never restate the title verbatim. Never use generic listicle phrasing."
)


class ThumbnailGenerator:

    def __init__(self) -> None:
        self._llm = get_llm()
        self._db  = get_db()
        self._font_path = self._find_font()

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(
        self,
        video_path:  str,
        title:       str,
        hook:        str,
        topic_name:  str,
        output_dir:  str,
        count:       int = 1,
    ) -> List[str]:
        """
        Generate `count` thumbnail JPEGs (1280x720) and return their local paths.
        Always returns at least one path — falls back to a plain frame with a
        topic-based overlay if the LLM or frame extraction misbehaves.
        """
        os.makedirs(output_dir, exist_ok=True)
        duration = self._probe_duration(video_path)

        texts = self._generate_texts(title, hook, topic_name, count)
        timestamps = self._pick_timestamps(duration, count)

        paths: List[str] = []
        for i in range(count):
            frame_path = os.path.join(output_dir, f"thumb_frame_{i}.jpg")
            out_path   = os.path.join(output_dir, f"thumbnail_{i}.jpg")

            extracted = self._extract_frame(video_path, timestamps[i], frame_path)
            if not extracted:
                self._solid_background(frame_path)

            self._compose(frame_path, texts[i], out_path)
            paths.append(out_path)

        logger.info("thumbnails_generated", topic=topic_name, count=len(paths), texts=texts)
        return paths

    # ── Text generation ──────────────────────────────────────────────────────

    def _generate_texts(self, title: str, hook: str, topic_name: str, count: int) -> List[str]:
        banned = self._load_banned_phrases()
        prompt = f"""Generate {count} thumbnail overlay text options for this video.

Title: {title}
Hook: {hook}
Topic: {topic_name}

Banned phrases (never use these or anything similar): {", ".join(banned)}

Return ONLY JSON: {{"texts": ["OPTION ONE", "OPTION TWO"]}}
Rules: each option is 2-4 words, ALL CAPS, creates curiosity without explaining everything."""

        try:
            data = self._llm.generate_json(prompt=prompt, system_prompt=_SYSTEM, max_tokens=150)
            texts = [str(t).strip().upper() for t in data.get("texts", []) if str(t).strip()]
            texts = [t for t in texts if not self._is_banned(t, banned)]
        except Exception as exc:
            logger.debug("thumbnail_text_llm_failed", error=str(exc)[:80])
            texts = []

        while len(texts) < count:
            texts.append(self._fallback_text(topic_name, len(texts)))

        return texts[:count]

    @staticmethod
    def _fallback_text(topic_name: str, index: int) -> str:
        options = [
            f"{topic_name.upper()}",
            "NOT WHAT YOU THINK",
            "SCIENTISTS SHOCKED",
            "THE HIDDEN TRUTH",
        ]
        return options[index % len(options)]

    def _load_banned_phrases(self) -> List[str]:
        try:
            style = self._db.get_config("thumbnail_style")
            if isinstance(style, dict):
                raw = style.get("banned_text", [])
                if isinstance(raw, list) and raw:
                    return [str(x).lower() for x in raw]
        except Exception:
            pass
        return list(_FALLBACK_BANNED)

    @staticmethod
    def _is_banned(text: str, banned: List[str]) -> bool:
        t = text.lower()
        return any(b in t for b in banned)

    # ── Frame extraction ──────────────────────────────────────────────────────

    @staticmethod
    def _pick_timestamps(duration: float, count: int) -> List[float]:
        if duration <= 0:
            return [0.5] * count
        fractions = [0.15, 0.55, 0.80, 0.35, 0.65]
        return [max(0.2, duration * fractions[i % len(fractions)]) for i in range(count)]

    @staticmethod
    def _extract_frame(video_path: str, timestamp: float, out_path: str) -> bool:
        cmd = [
            "ffmpeg", "-y", "-ss", str(timestamp), "-i", video_path,
            "-vf", f"scale={_W}:{_H}:force_original_aspect_ratio=increase,crop={_W}:{_H}",
            "-frames:v", "1", "-q:v", "2", out_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            return result.returncode == 0 and Path(out_path).exists() and Path(out_path).stat().st_size > 5_000
        except Exception:
            return False

    @staticmethod
    def _solid_background(out_path: str) -> None:
        img = Image.new("RGB", (_W, _H), color=(20, 30, 45))
        img.save(out_path, "JPEG", quality=90)

    @staticmethod
    def _probe_duration(path: str) -> float:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=10)
            data = json.loads(r.stdout)
            return float(data["format"].get("duration", 0) or 0)
        except Exception:
            return 0.0

    # ── Composition ───────────────────────────────────────────────────────────

    def _compose(self, frame_path: str, text: str, out_path: str) -> None:
        img = Image.open(frame_path).convert("RGB")
        if img.size != (_W, _H):
            img = img.resize((_W, _H))

        # Gradient overlay (bottom darkening for text legibility)
        gradient_h = int(_H * _GRADIENT_HEIGHT_RATIO)
        gradient = Image.new("L", (1, gradient_h), color=0)
        for y in range(gradient_h):
            alpha = int(190 * (y / gradient_h) ** 1.5)
            gradient.putpixel((0, y), alpha)
        gradient = gradient.resize((_W, gradient_h))

        overlay = Image.new("RGBA", (_W, _H), (0, 0, 0, 0))
        black_layer = Image.new("RGBA", (_W, gradient_h), (0, 0, 0, 255))
        black_layer.putalpha(gradient)
        overlay.paste(black_layer, (0, _H - gradient_h), black_layer)

        img = img.convert("RGBA")
        img = Image.alpha_composite(img, overlay)
        img = img.convert("RGB")

        # Text
        draw = ImageDraw.Draw(img)
        font_size = self._fit_font_size(draw, text, max_width=_W - 80)
        font = self._load_font(font_size)

        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=max(2, font_size // 18))
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (_W - text_w) // 2
        y = _H - text_h - int(_H * 0.08) - bbox[1]

        draw.text(
            (x, y), text, font=font,
            fill=(255, 255, 255),
            stroke_width=max(2, font_size // 18),
            stroke_fill=(0, 0, 0),
        )

        img.save(out_path, "JPEG", quality=92)

    def _fit_font_size(self, draw: ImageDraw.ImageDraw, text: str, max_width: int) -> int:
        size = 96
        min_size = 40
        while size > min_size:
            font = self._load_font(size)
            bbox = draw.textbbox((0, 0), text, font=font, stroke_width=max(2, size // 18))
            if (bbox[2] - bbox[0]) <= max_width:
                return size
            size -= 4
        return min_size

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont:
        if self._font_path:
            return ImageFont.truetype(self._font_path, size)
        return ImageFont.load_default()

    @staticmethod
    def _find_font() -> Optional[str]:
        for p in _FONT_PATHS:
            if Path(p).exists():
                return p
        return None


_instance: Optional[ThumbnailGenerator] = None

def get_thumbnail_generator() -> ThumbnailGenerator:
    global _instance
    if _instance is None:
        _instance = ThumbnailGenerator()
    return _instance
