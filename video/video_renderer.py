"""
video/video_renderer.py – Quizzaro Video Rendering Engine
===========================================================
Responsibilities:
  1. Draw all 8 Short templates frame-by-frame using Pillow + OpenCV
  2. Pop-up text animation (scale from 0 → 1 in 0.3s, inside Safe Area)
  3. Programmatic circular timer (green → red over 5 seconds)
  4. Phosphorescent green answer reveal with glow effect
  5. Blurred B-roll background (Pexels / Pixabay)
  6. Moving watermark @Quizzaro_1 at 30% opacity
  7. Random BGM slice (anti-Content-ID)
  8. Final FFmpeg assembly → MP4 (1080×1920, H.264, AAC)
  9. Random total duration tweak (±1.5s) for human-touch fingerprint

Output: a single .mp4 file path ready for YouTubeUploader.
"""

from __future__ import annotations

import math
import os
import random
import shutil
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import requests
from loguru import logger
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pydub import AudioSegment
from tinydb import TinyDB, Query

from core.content_engine import QuestionObject

# ── Output dirs ───────────────────────────────────────────────────────────────
RENDER_DIR = Path("data/render_tmp")
RENDER_DIR.mkdir(parents=True, exist_ok=True)
BG_CACHE_DIR = Path("data/bg_cache")
BG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
MUSIC_CACHE_DIR = Path("data/music_cache")
MUSIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
FONT_DIR = Path("data/fonts")
FONT_DIR.mkdir(parents=True, exist_ok=True)

# ── Video spec ────────────────────────────────────────────────────────────────
WIDTH = 1080
HEIGHT = 1920
FPS = 30
SAFE_LEFT = int(WIDTH * 0.08)
SAFE_RIGHT = int(WIDTH * 0.92)
SAFE_TOP = int(HEIGHT * 0.12)
SAFE_BOTTOM = int(HEIGHT * 0.88)
SAFE_W = SAFE_RIGHT - SAFE_LEFT
SAFE_H = SAFE_BOTTOM - SAFE_TOP

# ── Colors ────────────────────────────────────────────────────────────────────
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
PHOSPHOR_GREEN = (57, 255, 20)       # fluorescent green for answer reveal
TIMER_GREEN = (0, 230, 64)
TIMER_RED = (255, 45, 45)
OVERLAY_DARK = (0, 0, 0, 160)        # semi-transparent overlay RGBA
WATERMARK_COLOR = (255, 255, 255, 77)  # white @ 30% opacity

# ── Font URLs (Google Fonts – downloaded once) ────────────────────────────────
FONT_URLS = {
    "bold": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Bold.ttf",
    "extrabold": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-ExtraBold.ttf",
    "regular": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Regular.ttf",
}

# ── Anti-repeat DB ────────────────────────────────────────────────────────────
USED_DB = TinyDB("data/used_backgrounds.json")
USED_MUSIC_DB = TinyDB("data/used_music.json")
BG_REPEAT_DAYS = 10
MUSIC_REPEAT_DAYS = 7


# ─────────────────────────────────────────────────────────────────────────────
#  Font loader
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_fonts() -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name, url in FONT_URLS.items():
        dest = FONT_DIR / f"montserrat_{name}.ttf"
        if not dest.exists():
            logger.info(f"[Font] Downloading {name} font …")
            try:
                urllib.request.urlretrieve(url, dest)
            except Exception as exc:
                logger.warning(f"[Font] Download failed for {name}: {exc}")
                # fall back to PIL default
                dest = None
        paths[name] = dest
    return paths


FONTS = _ensure_fonts()


def _get_font(style: str = "bold", size: int = 60) -> ImageFont.FreeTypeFont:
    path = FONTS.get(style)
    if path and path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


# ─────────────────────────────────────────────────────────────────────────────
#  Background manager
# ─────────────────────────────────────────────────────────────────────────────

class BackgroundManager:
    """Fetches B-roll video clips from Pexels / Pixabay, applies blur, enforces 10-day repeat rule."""

    PEXELS_BASE = "https://api.pexels.com/videos/search"
    PIXABAY_BASE = "https://pixabay.com/api/videos/"

    BG_QUERIES = [
        "abstract motion", "particles bokeh", "nature timelapse", "city night",
        "galaxy stars", "ocean waves", "neon lights", "fire embers",
        "forest fog", "geometric shapes", "futuristic tunnel", "bokeh blur",
    ]

    def __init__(self, pexels_key: str, pixabay_key: str) -> None:
        self._pexels_key = pexels_key
        self._pixabay_key = pixabay_key
        self._db = USED_DB.table("backgrounds")

    def _is_used(self, video_id: str) -> bool:
        from datetime import datetime
        Q = Query()
        rows = self._db.search(Q.video_id == video_id)
        if not rows:
            return False
        delta = datetime.utcnow() - datetime.fromisoformat(rows[0]["used_at"])
        return delta.days < BG_REPEAT_DAYS

    def _mark_used(self, video_id: str) -> None:
        from datetime import datetime
        Q = Query()
        entry = {"video_id": video_id, "used_at": datetime.utcnow().isoformat()}
        if self._db.search(Q.video_id == video_id):
            self._db.update(entry, Q.video_id == video_id)
        else:
            self._db.insert(entry)

    def _fetch_pexels(self, query: str) -> Optional[dict]:
        try:
            resp = requests.get(
                self.PEXELS_BASE,
                headers={"Authorization": self._pexels_key},
                params={"query": query, "per_page": 15, "size": "medium", "orientation": "portrait"},
                timeout=15,
            )
            resp.raise_for_status()
            videos = resp.json().get("videos", [])
            random.shuffle(videos)
            for v in videos:
                vid_id = str(v["id"])
                if self._is_used(vid_id):
                    continue
                files = v.get("video_files", [])
                # prefer HD portrait
                files_sorted = sorted(files, key=lambda f: f.get("height", 0), reverse=True)
                for f in files_sorted:
                    if f.get("width", 0) <= f.get("height", 1):   # portrait
                        return {"id": vid_id, "url": f["link"], "source": "pexels"}
        except Exception as exc:
            logger.warning(f"[BG] Pexels failed: {exc}")
        return None

    def _fetch_pixabay(self, query: str) -> Optional[dict]:
        try:
            resp = requests.get(
                self.PIXABAY_BASE,
                params={
                    "key": self._pixabay_key,
                    "q": query,
                    "video_type": "animation",
                    "per_page": 15,
                    "safesearch": "true",
                },
                timeout=15,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
            random.shuffle(hits)
            for h in hits:
                vid_id = str(h["id"])
                if self._is_used(vid_id):
                    continue
                videos = h.get("videos", {})
                for quality in ("large", "medium", "small", "tiny"):
                    v = videos.get(quality, {})
                    if v.get("url"):
                        return {"id": vid_id, "url": v["url"], "source": "pixabay"}
        except Exception as exc:
            logger.warning(f"[BG] Pixabay failed: {exc}")
        return None

    def _download_video(self, url: str, dest: str) -> bool:
        try:
            resp = requests.get(url, timeout=60, stream=True)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            return True
        except Exception as exc:
            logger.error(f"[BG] Download error: {exc}")
            return False

    def get_background_frames(self, duration_sec: float, job_dir: Path) -> list[np.ndarray]:
        """
        Download a background clip, apply blur, extract frames at FPS.
        Returns list of BGR numpy arrays (HEIGHT × WIDTH × 3).
        Falls back to a solid dark gradient if download fails.
        """
        query = random.choice(self.BG_QUERIES)
        bg_path = str(job_dir / "background.mp4")
        meta = self._fetch_pexels(query) or self._fetch_pixabay(query)

        if meta and self._download_video(meta["url"], bg_path):
            self._mark_used(meta["id"])
            frames = self._extract_frames(bg_path, duration_sec)
            if frames:
                return [self._blur_and_resize(f) for f in frames]
            logger.warning("[BG] Frame extraction failed. Using gradient fallback.")
        else:
            logger.warning("[BG] No background video obtained. Using gradient fallback.")

        return self._make_gradient_frames(duration_sec)

    @staticmethod
    def _extract_frames(video_path: str, duration_sec: float) -> list[np.ndarray]:
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_fps = cap.get(cv2.CAP_PROP_FPS) or 30
        needed = int(duration_sec * FPS)
        frames: list[np.ndarray] = []

        if total_frames == 0:
            cap.release()
            return frames

        # Pick a random start point so we use a different segment each time
        max_start = max(0, total_frames - int(duration_sec * video_fps) - 1)
        start_frame = random.randint(0, max_start) if max_start > 0 else 0
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        indices = np.linspace(0, int(duration_sec * video_fps) - 1, needed, dtype=int)
        raw: list[np.ndarray] = []
        for _ in range(int(duration_sec * video_fps)):
            ret, frame = cap.read()
            if not ret:
                break
            raw.append(frame)
        cap.release()

        for i in indices:
            idx = min(i, len(raw) - 1)
            frames.append(raw[idx])
        return frames

    @staticmethod
    def _blur_and_resize(frame: np.ndarray) -> np.ndarray:
        # Resize to cover 1080×1920 (crop center)
        h, w = frame.shape[:2]
        scale = max(WIDTH / w, HEIGHT / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(frame, (new_w, new_h))
        x = (new_w - WIDTH) // 2
        y = (new_h - HEIGHT) // 2
        cropped = resized[y:y + HEIGHT, x:x + WIDTH]
        # Heavy Gaussian blur (simulated depth of field)
        blurred = cv2.GaussianBlur(cropped, (51, 51), 0)
        return blurred

    @staticmethod
    def _make_gradient_frames(duration_sec: float) -> list[np.ndarray]:
        needed = int(duration_sec * FPS)
        base = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        # Dark purple→blue gradient
        for y in range(HEIGHT):
            t = y / HEIGHT
            base[y, :] = [
                int(20 + t * 10),
                int(10 + t * 20),
                int(40 + t * 60),
            ]
        return [base.copy() for _ in range(needed)]


# ─────────────────────────────────────────────────────────────────────────────
#  Music engine
# ─────────────────────────────────────────────────────────────────────────────

class MusicEngine:
    """Fetches free lofi/quiz BGM from Freesound, cuts a random slice (anti-ContentID)."""

    MUSIC_QUERIES = [
        "lofi quiz background music", "chill background instrumental",
        "quiz show music background", "educational background music calm",
        "upbeat background music no copyright",
    ]

    def __init__(self, freesound_api_key: str) -> None:
        self._api_key = freesound_api_key
        self._db = USED_MUSIC_DB.table("music")

    def _is_used(self, sound_id: str) -> bool:
        from datetime import datetime
        Q = Query()
        rows = self._db.search(Q.sound_id == sound_id)
        if not rows:
            return False
        delta = datetime.utcnow() - datetime.fromisoformat(rows[0]["used_at"])
        return delta.days < MUSIC_REPEAT_DAYS

    def _mark_used(self, sound_id: str) -> None:
        from datetime import datetime
        Q = Query()
        entry = {"sound_id": sound_id, "used_at": datetime.utcnow().isoformat()}
        if self._db.search(Q.sound_id == sound_id):
            self._db.update(entry, Q.sound_id == sound_id)
        else:
            self._db.insert(entry)

    def get_bgm(self, duration_ms: int, dest_path: str) -> Optional[str]:
        query = random.choice(self.MUSIC_QUERIES)
        try:
            resp = requests.get(
                "https://freesound.org/apiv2/search/text/",
                params={
                    "query": query,
                    "filter": 'duration:[30 TO 300] license:"Creative Commons 0"',
                    "fields": "id,name,previews,duration",
                    "page_size": 15,
                    "token": self._api_key,
                },
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            random.shuffle(results)

            for sound in results:
                sid = str(sound["id"])
                if self._is_used(sid):
                    continue
                preview_url = sound.get("previews", {}).get("preview-hq-mp3") or \
                              sound.get("previews", {}).get("preview-lq-mp3")
                if not preview_url:
                    continue
                dl_resp = requests.get(preview_url, timeout=30)
                dl_resp.raise_for_status()
                raw_path = dest_path.replace(".wav", "_raw.mp3")
                with open(raw_path, "wb") as f:
                    f.write(dl_resp.content)

                # Cut a random slice to defeat Content-ID fingerprinting
                audio = AudioSegment.from_file(raw_path)
                if len(audio) > duration_ms + 5000:
                    max_start = len(audio) - duration_ms - 1000
                    start = random.randint(0, max_start)
                    audio = audio[start: start + duration_ms + 2000]

                # Fade in/out to avoid hard cuts
                audio = audio.fade_in(500).fade_out(1000)
                audio = audio.set_frame_rate(44100).set_channels(2)
                audio.export(dest_path, format="wav")
                self._mark_used(sid)
                return dest_path

        except Exception as exc:
            logger.warning(f"[Music] Failed: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  Frame drawing helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pil_from_bgr(frame: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def _bgr_from_pil(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _draw_text_with_stroke(
    draw: ImageDraw.Draw,
    text: str,
    position: tuple[int, int],
    font: ImageFont.FreeTypeFont,
    fill: tuple,
    stroke_width: int = 4,
    stroke_fill: tuple = BLACK,
    align: str = "center",
) -> None:
    x, y = position
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=stroke_fill, anchor="mm", align=align)
    draw.text((x, y), text, font=font, fill=fill, anchor="mm", align=align)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""
    dummy_img = Image.new("RGB", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)

    for word in words:
        test = f"{current} {word}".strip()
        bbox = dummy_draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_multiline_centered(
    draw: ImageDraw.Draw,
    lines: list[str],
    center_x: int,
    center_y: int,
    font: ImageFont.FreeTypeFont,
    fill: tuple,
    stroke_width: int = 4,
    line_spacing: int = 12,
) -> int:
    """Draw multiple lines centered on center_x/center_y. Returns bottom Y."""
    dummy_img = Image.new("RGB", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    line_heights = []
    for line in lines:
        bbox = dummy_draw.textbbox((0, 0), line, font=font)
        line_heights.append(bbox[3] - bbox[1])

    total_h = sum(line_heights) + line_spacing * (len(lines) - 1)
    y = center_y - total_h // 2
    for i, line in enumerate(lines):
        _draw_text_with_stroke(draw, line, (center_x, y + line_heights[i] // 2), font, fill, stroke_width)
        y += line_heights[i] + line_spacing
    return y


def _draw_dark_overlay(img: Image.Image, alpha: int = 160) -> Image.Image:
    """Apply a semi-transparent dark overlay for text readability."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, alpha))
    base = img.convert("RGBA")
    combined = Image.alpha_composite(base, overlay)
    return combined.convert("RGB")


# ─────────────────────────────────────────────────────────────────────────────
#  Circular Timer renderer
# ─────────────────────────────────────────────────────────────────────────────

def _draw_circular_timer(
    img: Image.Image,
    progress: float,          # 0.0 (full) → 1.0 (empty)
    center: tuple[int, int],
    radius: int = 90,
    thickness: int = 14,
) -> Image.Image:
    """
    Draw a countdown arc that sweeps from green to red as progress → 1.
    progress=0 → full green circle; progress=1 → full red circle.
    """
    draw = ImageDraw.Draw(img, "RGBA")
    cx, cy = center

    # Background ring (dark grey)
    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.arc(bbox, start=0, end=360, fill=(60, 60, 60, 200), width=thickness)

    # Interpolate color green → yellow → red
    if progress < 0.5:
        t = progress / 0.5
        r = int(TIMER_GREEN[0] + t * (255 - TIMER_GREEN[0]))
        g = int(TIMER_GREEN[1] + t * (200 - TIMER_GREEN[1]))
        b = int(TIMER_GREEN[2])
    else:
        t = (progress - 0.5) / 0.5
        r = 255
        g = int(200 - t * 155)
        b = int(TIMER_GREEN[2])
    arc_color = (r, g, b, 255)

    # Sweep angle: starts at -90° (top), goes clockwise
    remaining_angle = 360 * (1.0 - progress)
    end_angle = -90 + remaining_angle
    if remaining_angle > 0.5:
        draw.arc(bbox, start=-90, end=end_angle, fill=arc_color, width=thickness)

    # Timer digit
    seconds_left = max(0, math.ceil(5 * (1.0 - progress)))
    font = _get_font("extrabold", size=int(radius * 0.9))
    _draw_text_with_stroke(draw, str(seconds_left), center, font, WHITE, stroke_width=3)

    return img


# ─────────────────────────────────────────────────────────────────────────────
#  Watermark engine
# ─────────────────────────────────────────────────────────────────────────────

class WatermarkEngine:
    """Slow-moving @Quizzaro_1 watermark at 30% opacity."""

    def __init__(self, handle: str = "@Quizzaro_1") -> None:
        self._handle = handle
        self._font = _get_font("regular", size=32)

    def apply(self, img: Image.Image, frame_index: int, total_frames: int) -> Image.Image:
        """Move the watermark slowly from left→right and top→bottom over the video duration."""
        t = frame_index / max(total_frames - 1, 1)   # 0.0 → 1.0

        # Horizontal: left safe → right safe over full duration
        x = int(SAFE_LEFT + t * (SAFE_W - 200))
        # Vertical: slow sine wave for organic movement
        y = int(HEIGHT * 0.08 + math.sin(t * math.pi) * HEIGHT * 0.05)

        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.text((x, y), self._handle, font=self._font, fill=WATERMARK_COLOR)
        base = img.convert("RGBA")
        combined = Image.alpha_composite(base, overlay)
        return combined.convert("RGB")


# ─────────────────────────────────────────────────────────────────────────────
#  Pop-up text animation
# ─────────────────────────────────────────────────────────────────────────────

def _popup_scale(frame_in_anim: int, anim_frames: int) -> float:
    """
    Ease-out scale: starts at 0.0, reaches 1.0 over anim_frames frames.
    Uses cubic ease-out for snappy pop-up feel.
    """
    t = min(frame_in_anim / anim_frames, 1.0)
    return 1.0 - (1.0 - t) ** 3


# ─────────────────────────────────────────────────────────────────────────────
#  Answer reveal glow
# ─────────────────────────────────────────────────────────────────────────────

def _draw_answer_reveal(img: Image.Image, answer_text: str, frame_in_reveal: int) -> Image.Image:
    """
    Draw phosphorescent green answer with bloom glow effect.
    frame_in_reveal=0 is the first frame of the reveal section.
    """
    draw_img = img.copy().convert("RGBA")

    # Glow layer: blurred green text behind the sharp text
    glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    font_size = 80 if len(answer_text) < 15 else 60
    font = _get_font("extrabold", font_size)

    lines = _wrap_text(answer_text, font, SAFE_W - 40)
    cx = WIDTH // 2
    cy = HEIGHT // 2 + 80

    # Draw green text multiple times with blur to simulate glow
    for _ in range(3):
        _draw_multiline_centered(gd, lines, cx, cy, font, PHOSPHOR_GREEN + (120,), stroke_width=0)

    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=18))

    # Sharp text on top
    sharp_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sharp_layer)
    _draw_multiline_centered(sd, lines, cx, cy, font, PHOSPHOR_GREEN + (255,), stroke_width=5)

    # Pulse alpha based on frame (brief flash on first 6 frames)
    pulse = min(1.0, frame_in_reveal / 6)
    glow_alpha = int(255 * pulse)
    glow_layer.putalpha(ImageDraw.ImageDraw(glow_layer))  # keep existing alpha

    result = Image.alpha_composite(draw_img, glow_layer)
    result = Image.alpha_composite(result, sharp_layer)
    return result.convert("RGB")


# ─────────────────────────────────────────────────────────────────────────────
#  Template renderers  (all 8 templates share the same base pipeline)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RenderJob:
    question: QuestionObject
    bg_frames: list[np.ndarray]
    total_frames: int
    question_end_frame: int      # when answer reveal starts (after timer)
    timer_start_frame: int
    timer_end_frame: int
    answer_reveal_frame: int
    job_dir: Path
    watermark: WatermarkEngine


def _render_frame(job: RenderJob, frame_idx: int) -> np.ndarray:
    """Render a single video frame."""
    bg_idx = min(frame_idx, len(job.bg_frames) - 1)
    bg = _pil_from_bgr(job.bg_frames[bg_idx])

    # Dark overlay for readability
    img = _draw_dark_overlay(bg, alpha=155)

    q = job.question
    cx = WIDTH // 2

    # ── Phase 1: Question display ──────────────────────────────────────────
    if frame_idx < job.timer_start_frame:
        phase_frame = frame_idx
        anim_dur = int(FPS * 0.35)   # 0.35s pop-up animation

        scale = _popup_scale(phase_frame, anim_dur)

        # Template badge (top area)
        badge_font = _get_font("bold", 36)
        badge_text = q.template.replace("_", " ").upper()
        badge_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
        bd = ImageDraw.Draw(badge_img)
        # Rounded badge background
        badge_x1, badge_y1 = cx - 160, SAFE_TOP + 30
        badge_x2, badge_y2 = cx + 160, SAFE_TOP + 80
        bd.rounded_rectangle([badge_x1, badge_y1, badge_x2, badge_y2], radius=20, fill=(255, 200, 0, 220))
        bd.text((cx, (badge_y1 + badge_y2) // 2), badge_text, font=badge_font, fill=(0, 0, 0), anchor="mm")
        img = Image.alpha_composite(img.convert("RGBA"), badge_img).convert("RGB")

        # Question text with pop-up scale
        font_size = max(40, min(72, int(72 * scale)))
        q_font = _get_font("extrabold", font_size)
        lines = _wrap_text(q.question_text, q_font, SAFE_W - 20)
        draw = ImageDraw.Draw(img)

        alpha_val = int(255 * min(1.0, scale * 1.5))
        text_color = (255, 255, 255, alpha_val) if scale < 1.0 else WHITE

        text_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
        td = ImageDraw.Draw(text_img)
        _draw_multiline_centered(td, lines, cx, HEIGHT // 2 - 60, q_font, (255, 255, 255, alpha_val), stroke_width=5)
        img = Image.alpha_composite(img.convert("RGBA"), text_img).convert("RGB")

        # CTA text (smaller, below question)
        if phase_frame > int(FPS * 0.5):
            cta_font = _get_font("regular", 32)
            cta_lines = _wrap_text(q.cta_text, cta_font, SAFE_W - 40)
            cta_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
            cd = ImageDraw.Draw(cta_img)
            _draw_multiline_centered(cd, cta_lines, cx, HEIGHT // 2 + 220, cta_font, (255, 230, 100, 200), stroke_width=3)
            img = Image.alpha_composite(img.convert("RGBA"), cta_img).convert("RGB")

        # For multiple_choice: show options
        if q.template == "multiple_choice" and phase_frame > int(FPS * 0.7) and q.wrong_answers:
            all_options = [q.correct_answer] + q.wrong_answers[:3]
            random.shuffle(all_options)
            opt_font = _get_font("bold", 38)
            labels = ["A", "B", "C", "D"]
            opt_start_y = HEIGHT // 2 + 120
            opt_spacing = 90
            for i, (label, opt) in enumerate(zip(labels, all_options)):
                oy = opt_start_y + i * opt_spacing
                opt_bg = Image.new("RGBA", img.size, (0, 0, 0, 0))
                od = ImageDraw.Draw(opt_bg)
                od.rounded_rectangle(
                    [SAFE_LEFT, oy - 30, SAFE_RIGHT, oy + 30],
                    radius=15,
                    fill=(255, 255, 255, 40),
                )
                od.text((SAFE_LEFT + 20, oy), f"{label}.  {opt}", font=opt_font, fill=(255, 255, 255), anchor="lm")
                img = Image.alpha_composite(img.convert("RGBA"), opt_bg).convert("RGB")

        # For true_false: show T/F buttons
        if q.template == "true_false" and phase_frame > int(FPS * 0.7):
            tf_font = _get_font("extrabold", 52)
            draw = ImageDraw.Draw(img.convert("RGBA"))
            tf_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
            tfd = ImageDraw.Draw(tf_img)
            # TRUE button
            tfd.rounded_rectangle([SAFE_LEFT, HEIGHT // 2 + 180, cx - 20, HEIGHT // 2 + 280], radius=20, fill=(0, 200, 80, 200))
            tfd.text(((SAFE_LEFT + cx - 20) // 2, HEIGHT // 2 + 230), "TRUE", font=tf_font, fill=WHITE, anchor="mm")
            # FALSE button
            tfd.rounded_rectangle([cx + 20, HEIGHT // 2 + 180, SAFE_RIGHT, HEIGHT // 2 + 280], radius=20, fill=(220, 50, 50, 200))
            tfd.text(((cx + 20 + SAFE_RIGHT) // 2, HEIGHT // 2 + 230), "FALSE", font=tf_font, fill=WHITE, anchor="mm")
            img = Image.alpha_composite(img.convert("RGBA"), tf_img).convert("RGB")

    # ── Phase 2: Timer countdown ───────────────────────────────────────────
    elif frame_idx < job.timer_end_frame:
        timer_frame = frame_idx - job.timer_start_frame
        timer_total = job.timer_end_frame - job.timer_start_frame
        progress = timer_frame / timer_total

        # Keep question text visible but dimmer
        q_font = _get_font("extrabold", 60)
        lines = _wrap_text(q.question_text, q_font, SAFE_W - 20)
        text_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
        td = ImageDraw.Draw(text_img)
        _draw_multiline_centered(td, lines, cx, HEIGHT // 2 - 180, q_font, (255, 255, 255, 180), stroke_width=5)
        img = Image.alpha_composite(img.convert("RGBA"), text_img).convert("RGB")

        # Circular timer centered
        timer_center = (cx, HEIGHT // 2 + 100)
        img_pil = img.convert("RGBA")
        img_pil = _draw_circular_timer(img_pil, progress, timer_center, radius=110, thickness=18)
        img = img_pil.convert("RGB")

        # "Time's running out!" text pulse
        if progress > 0.6:
            pulse_font = _get_font("bold", 38)
            p_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
            pd = ImageDraw.Draw(p_img)
            alpha_pulse = int(128 + 127 * math.sin(timer_frame * 0.4))
            pd.text((cx, HEIGHT // 2 + 280), "⏳ Hurry up!", font=pulse_font,
                    fill=(255, 220, 50, alpha_pulse), anchor="mm")
            img = Image.alpha_composite(img.convert("RGBA"), p_img).convert("RGB")

    # ── Phase 3: Answer reveal ─────────────────────────────────────────────
    else:
        reveal_frame = frame_idx - job.answer_reveal_frame
        img = _draw_answer_reveal(img, q.correct_answer, reveal_frame)

        # Explanation text below answer
        exp_font = _get_font("regular", 34)
        if q.explanation and reveal_frame > int(FPS * 0.5):
            exp_lines = _wrap_text(q.explanation, exp_font, SAFE_W - 40)
            exp_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ed = ImageDraw.Draw(exp_img)
            _draw_multiline_centered(ed, exp_lines, cx, HEIGHT // 2 + 260, exp_font,
                                     (200, 200, 200, 200), stroke_width=2)
            img = Image.alpha_composite(img.convert("RGBA"), exp_img).convert("RGB")

        # "✓ CORRECT!" badge
        badge_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
        bd = ImageDraw.Draw(badge_img)
        badge_font = _get_font("extrabold", 52)
        bx1, by1 = cx - 180, HEIGHT // 2 - 200
        bx2, by2 = cx + 180, HEIGHT // 2 - 130
        bd.rounded_rectangle([bx1, by1, bx2, by2], radius=25, fill=(57, 255, 20, 200))
        bd.text((cx, (by1 + by2) // 2), "✓  CORRECT!", font=badge_font, fill=BLACK, anchor="mm")
        img = Image.alpha_composite(img.convert("RGBA"), badge_img).convert("RGB")

    # ── Watermark (every frame) ────────────────────────────────────────────
    img = job.watermark.apply(img, frame_idx, job.total_frames)

    return _bgr_from_pil(img)


# ─────────────────────────────────────────────────────────────────────────────
#  Video Renderer (master class)
# ─────────────────────────────────────────────────────────────────────────────

class VideoRenderer:
    """
    Orchestrates full Short video production end-to-end.
    Called by VideoComposer / main.py for each Short.
    """

    QUESTION_DISPLAY_SEC = 4.0
    TIMER_SEC = 5.0
    ANSWER_SEC = 5.0
    BASE_DURATION = QUESTION_DISPLAY_SEC + TIMER_SEC + ANSWER_SEC  # 14s

    def __init__(
        self,
        pexels_key: str,
        pixabay_key: str,
        freesound_api_key: str,
    ) -> None:
        self._bg = BackgroundManager(pexels_key, pixabay_key)
        self._music = MusicEngine(freesound_api_key)
        self._watermark = WatermarkEngine()

    def render(self, question: QuestionObject, audio_engine, job_id: str) -> str:
        """
        Full render pipeline.
        Returns path to the final .mp4 file.
        """
        from audio.audio_engine import AudioEngine

        job_dir = RENDER_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        # ── Random duration tweak (human-touch fingerprint) ────────────────
        duration_jitter = random.uniform(-1.2, 1.5)
        extra_q_sec = max(0.0, duration_jitter)
        total_sec = self.BASE_DURATION + extra_q_sec
        q_display_sec = self.QUESTION_DISPLAY_SEC + extra_q_sec

        total_frames = int(total_sec * FPS)
        timer_start_frame = int(q_display_sec * FPS)
        timer_end_frame = timer_start_frame + int(self.TIMER_SEC * FPS)
        answer_reveal_frame = timer_end_frame

        logger.info(f"[Renderer] {job_id} | duration={total_sec:.1f}s | frames={total_frames}")

        # ── 1. Background frames ───────────────────────────────────────────
        bg_frames = self._bg.get_background_frames(total_sec, job_dir)

        # ── 2. Audio voiceover ─────────────────────────────────────────────
        audio_result = audio_engine.render_question_audio(
            question_text=question.question_text,
            cta_text=question.cta_text,
            job_id=job_id,
        )

        # ── 3. Background music ────────────────────────────────────────────
        bgm_path = str(job_dir / "bgm.wav")
        bgm_result = self._music.get_bgm(int(total_sec * 1000), bgm_path)
        if bgm_result:
            bgm_audio = AudioSegment.from_file(bgm_path)
        else:
            bgm_audio = AudioSegment.silent(duration=int(total_sec * 1000))

        # ── 4. Mix final audio track ───────────────────────────────────────
        mixed_audio = audio_engine.mix_final_audio(
            question_vo_path=audio_result["question_vo"],
            cta_vo_path=audio_result["cta_vo"],
            tick_tock=audio_engine.get_tick_tock(duration_ms=int(self.TIMER_SEC * 1000)),
            answer_sfx=audio_engine.get_answer_sfx(),
            background_music=bgm_audio,
            timer_start_ms=int(q_display_sec * 1000),
            answer_reveal_ms=int((q_display_sec + self.TIMER_SEC) * 1000),
            total_duration_ms=int(total_sec * 1000),
        )
        audio_path = str(job_dir / "final_audio.wav")
        mixed_audio.export(audio_path, format="wav")

        # ── 5. Build RenderJob ─────────────────────────────────────────────
        render_job = RenderJob(
            question=question,
            bg_frames=bg_frames,
            total_frames=total_frames,
            question_end_frame=timer_start_frame,
            timer_start_frame=timer_start_frame,
            timer_end_frame=timer_end_frame,
            answer_reveal_frame=answer_reveal_frame,
            job_dir=job_dir,
            watermark=self._watermark,
        )

        # ── 6. Write video frames ──────────────────────────────────────────
        frames_dir = job_dir / "frames"
        frames_dir.mkdir(exist_ok=True)

        logger.info(f"[Renderer] Writing {total_frames} frames …")
        for i in range(total_frames):
            frame = _render_frame(render_job, i)
            frame_path = frames_dir / f"frame_{i:05d}.png"
            cv2.imwrite(str(frame_path), frame)

        # ── 7. FFmpeg assembly ─────────────────────────────────────────────
        output_path = str(job_dir / "final_short.mp4")
        self._ffmpeg_assemble(str(frames_dir), audio_path, output_path, total_sec)

        # ── 8. Cleanup temp frames ─────────────────────────────────────────
        shutil.rmtree(str(frames_dir), ignore_errors=True)

        logger.success(f"[Renderer] Done: {output_path}")
        return output_path

    @staticmethod
    def _ffmpeg_assemble(frames_dir: str, audio_path: str, output_path: str, duration: float) -> None:
        """Combine PNG frames + WAV audio into final H.264/AAC MP4."""
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", f"{frames_dir}/frame_%05d.png",
            "-i", audio_path,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            "-t", f"{duration:.2f}",
            output_path,
        ]
        logger.info(f"[FFmpeg] Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed:\n{result.stderr}")
        logger.success(f"[FFmpeg] Output: {output_path}")
