"""
video/video_renderer.py – Quizzaro Video Rendering Engine
"""

from __future__ import annotations

import math
import os
import random
import re
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

RENDER_DIR = Path("data/render_tmp")
RENDER_DIR.mkdir(parents=True, exist_ok=True)
BG_CACHE_DIR = Path("data/bg_cache")
BG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
MUSIC_CACHE_DIR = Path("data/music_cache")
MUSIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
FONT_DIR = Path("data/fonts")
FONT_DIR.mkdir(parents=True, exist_ok=True)

WIDTH = 1080
HEIGHT = 1920
FPS = 30
SAFE_LEFT = int(WIDTH * 0.08)
SAFE_RIGHT = int(WIDTH * 0.92)
SAFE_TOP = int(HEIGHT * 0.12)
SAFE_BOTTOM = int(HEIGHT * 0.88)
SAFE_W = SAFE_RIGHT - SAFE_LEFT
SAFE_H = SAFE_BOTTOM - SAFE_TOP

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
PHOSPHOR_GREEN = (57, 255, 20)
TIMER_GREEN = (0, 230, 64)
TIMER_RED = (255, 45, 45)
OVERLAY_DARK = (0, 0, 0, 140)
WATERMARK_COLOR = (255, 255, 255, 77)

FONT_URLS = {
    "bold": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Bold.ttf",
    "extrabold": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-ExtraBold.ttf",
    "regular": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Regular.ttf",
}

USED_DB = TinyDB("data/used_backgrounds.json")
USED_MUSIC_DB = TinyDB("data/used_music.json")
BG_REPEAT_DAYS = 10
MUSIC_REPEAT_DAYS = 7

def _ensure_fonts() -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name, url in FONT_URLS.items():
        dest = FONT_DIR / f"montserrat_{name}.ttf"
        if not dest.exists():
            logger.info(f"[Font] Downloading {name} font …")
            try: urllib.request.urlretrieve(url, dest)
            except Exception as exc: dest = None
        paths[name] = dest
    return paths

FONTS = _ensure_fonts()

def _get_font(style: str = "bold", size: int = 60) -> ImageFont.FreeTypeFont:
    path = FONTS.get(style)
    if path and path.exists(): return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()

class BackgroundManager:
    PEXELS_BASE = "https://api.pexels.com/videos/search"
    PIXABAY_BASE = "https://pixabay.com/api/videos/"

    BG_QUERIES = [
        "cyberpunk city", "neon abstract loop", "fast motion graphics", 
        "satisfying loop 3d", "gaming background abstract", "futuristic tech tunnel",
        "synthwave lights", "kinetic typography background", "liquid metal 3d"
    ]

    def __init__(self, pexels_key: str, pixabay_key: str) -> None:
        self._pexels_key = pexels_key
        self._pixabay_key = pixabay_key
        self._db = USED_DB.table("backgrounds")

    def _is_used(self, video_id: str) -> bool:
        from datetime import datetime
        Q = Query()
        rows = self._db.search(Q.video_id == video_id)
        if not rows: return False
        return (datetime.utcnow() - datetime.fromisoformat(rows[0]["used_at"])).days < BG_REPEAT_DAYS

    def _mark_used(self, video_id: str) -> None:
        from datetime import datetime
        Q = Query()
        entry = {"video_id": video_id, "used_at": datetime.utcnow().isoformat()}
        if self._db.search(Q.video_id == video_id): self._db.update(entry, Q.video_id == video_id)
        else: self._db.insert(entry)

    def _fetch_pexels(self, query: str) -> Optional[dict]:
        try:
            resp = requests.get(self.PEXELS_BASE, headers={"Authorization": self._pexels_key}, params={"query": query, "per_page": 15, "size": "medium", "orientation": "portrait"}, timeout=15)
            resp.raise_for_status()
            videos = resp.json().get("videos", [])
            random.shuffle(videos)
            for v in videos:
                vid_id = str(v["id"])
                if self._is_used(vid_id): continue
                for f in sorted(v.get("video_files", []), key=lambda x: x.get("height", 0), reverse=True):
                    if f.get("width", 0) <= f.get("height", 1): return {"id": vid_id, "url": f["link"], "source": "pexels"}
        except Exception: pass
        return None

    def _fetch_pixabay(self, query: str) -> Optional[dict]:
        try:
            resp = requests.get(self.PIXABAY_BASE, params={"key": self._pixabay_key, "q": query, "video_type": "animation", "per_page": 15, "safesearch": "true"}, timeout=15)
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
            random.shuffle(hits)
            for h in hits:
                vid_id = str(h["id"])
                if self._is_used(vid_id): continue
                videos = h.get("videos", {})
                for quality in ("large", "medium", "small", "tiny"):
                    if videos.get(quality, {}).get("url"): return {"id": vid_id, "url": videos[quality]["url"], "source": "pixabay"}
        except Exception: pass
        return None

    def _download_video(self, url: str, dest: str) -> bool:
        try:
            resp = requests.get(url, timeout=60, stream=True)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536): f.write(chunk)
            return True
        except Exception: return False

    def get_background_frames(self, duration_sec: float, job_dir: Path) -> list[np.ndarray]:
        query = random.choice(self.BG_QUERIES)
        bg_path = str(job_dir / "background.mp4")
        meta = self._fetch_pexels(query) or self._fetch_pixabay(query)
        if meta and self._download_video(meta["url"], bg_path):
            self._mark_used(meta["id"])
            frames = self._extract_frames(bg_path, duration_sec)
            if frames: return [self._blur_and_resize(f) for f in frames]
        return self._make_gradient_frames(duration_sec)

    @staticmethod
    def _extract_frames(video_path: str, duration_sec: float) -> list[np.ndarray]:
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_fps = cap.get(cv2.CAP_PROP_FPS) or 30
        needed = int(duration_sec * FPS)
        if total_frames == 0:
            cap.release()
            return []
        start_frame = random.randint(0, max(0, total_frames - int(duration_sec * video_fps) - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        raw: list[np.ndarray] = []
        for _ in range(int(duration_sec * video_fps)):
            ret, frame = cap.read()
            if not ret: break
            raw.append(frame)
        cap.release()
        return [raw[min(i, len(raw) - 1)] for i in np.linspace(0, len(raw) - 1, needed, dtype=int)]

    @staticmethod
    def _blur_and_resize(frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        scale = max(WIDTH / w, HEIGHT / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(frame, (new_w, new_h))
        x, y = (new_w - WIDTH) // 2, (new_h - HEIGHT) // 2
        return cv2.GaussianBlur(resized[y:y + HEIGHT, x:x + WIDTH], (35, 35), 0)

    @staticmethod
    def _make_gradient_frames(duration_sec: float) -> list[np.ndarray]:
        needed = int(duration_sec * FPS)
        base = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        for y in range(HEIGHT):
            t = y / HEIGHT
            base[y, :] = [int(20 + t * 10), int(10 + t * 20), int(40 + t * 60)]
        return [base.copy() for _ in range(needed)]


class MusicEngine:
    MUSIC_QUERIES = [
        "suspense clock ticking", "fast electronic beat", "phonk instrumental", 
        "epic quiz timer", "intense cinematic loop", "cyberpunk synthwave fast"
    ]

    def __init__(self, freesound_api_key: str) -> None:
        self._api_key = freesound_api_key
        self._db = USED_MUSIC_DB.table("music")

    def _is_used(self, sound_id: str) -> bool:
        from datetime import datetime
        Q = Query()
        rows = self._db.search(Q.sound_id == sound_id)
        if not rows: return False
        return (datetime.utcnow() - datetime.fromisoformat(rows[0]["used_at"])).days < MUSIC_REPEAT_DAYS

    def _mark_used(self, sound_id: str) -> None:
        from datetime import datetime
        Q = Query()
        entry = {"sound_id": sound_id, "used_at": datetime.utcnow().isoformat()}
        if self._db.search(Q.sound_id == sound_id): self._db.update(entry, Q.sound_id == sound_id)
        else: self._db.insert(entry)

    def get_bgm(self, duration_ms: int, dest_path: str) -> Optional[str]:
        query = random.choice(self.MUSIC_QUERIES)
        try:
            resp = requests.get(
                "https://freesound.org/apiv2/search/text/",
                params={"query": query, "filter": 'duration:[15 TO 300] license:"Creative Commons 0"', "fields": "id,name,previews,duration", "page_size": 15, "token": self._api_key},
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            random.shuffle(results)
            for sound in results:
                sid = str(sound["id"])
                if self._is_used(sid): continue
                preview_url = sound.get("previews", {}).get("preview-hq-mp3") or sound.get("previews", {}).get("preview-lq-mp3")
                if not preview_url: continue
                dl_resp = requests.get(preview_url, timeout=30)
                dl_resp.raise_for_status()
                raw_path = dest_path.replace(".wav", "_raw.mp3")
                with open(raw_path, "wb") as f: f.write(dl_resp.content)
                audio = AudioSegment.from_file(raw_path)
                if len(audio) > duration_ms + 5000:
                    start = random.randint(0, len(audio) - duration_ms - 1000)
                    audio = audio[start: start + duration_ms + 2000]
                audio.fade_in(500).fade_out(1000).set_frame_rate(44100).set_channels(2).export(dest_path, format="wav")
                self._mark_used(sid)
                return dest_path
        except Exception: pass
        return None

def _pil_from_bgr(frame: np.ndarray) -> Image.Image: return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
def _bgr_from_pil(img: Image.Image) -> np.ndarray: return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

def _draw_text_with_stroke(draw: ImageDraw.Draw, text: str, position: tuple[int, int], font: ImageFont.FreeTypeFont, fill: tuple, stroke_width: int = 4, stroke_fill: tuple = BLACK, align: str = "center", anchor="mm") -> None:
    x, y = position
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=stroke_fill, anchor=anchor, align=align)
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor, align=align)

def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines, current = [], ""
    dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for word in words:
        test = f"{current} {word}".strip()
        if dummy_draw.textbbox((0, 0), test, font=font)[2] <= max_width: current = test
        else:
            if current: lines.append(current)
            current = word
    if current: lines.append(current)
    return lines

def _draw_multiline_centered(draw: ImageDraw.Draw, lines: list[str], center_x: int, center_y: int, font: ImageFont.FreeTypeFont, fill: tuple, stroke_width: int = 4, line_spacing: int = 12) -> int:
    dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    line_heights = [dummy_draw.textbbox((0, 0), line, font=font)[3] - dummy_draw.textbbox((0, 0), line, font=font)[1] for line in lines]
    y = center_y - (sum(line_heights) + line_spacing * (len(lines) - 1)) // 2
    for i, line in enumerate(lines):
        _draw_text_with_stroke(draw, line, (center_x, y + line_heights[i] // 2), font, fill, stroke_width)
        y += line_heights[i] + line_spacing
    return y

def _draw_dark_overlay(img: Image.Image, alpha: int = 160) -> Image.Image:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, alpha))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

def _draw_levels_sidebar(img: Image.Image, active_idx: int) -> Image.Image:
    levels = [("EASY", (57, 255, 20)), ("MEDIUM", (255, 255, 0)), ("HARD", (255, 165, 0)), ("EXPERT", (255, 45, 45))]
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font, title_font = _get_font("extrabold", 38), _get_font("bold", 32)
    start_y = HEIGHT // 2 - 250
    _draw_text_with_stroke(draw, "LEVEL", (SAFE_LEFT + 130, start_y - 60), title_font, WHITE, stroke_width=2)
    for i, (text, color) in enumerate(levels):
        y = start_y + i * 110
        bg_color, txt_color = (color + (255,), BLACK) if i == active_idx else (color + (100,), WHITE) if i < active_idx else ((40, 40, 40, 150), (200, 200, 200, 255))
        draw.rounded_rectangle([SAFE_LEFT, y, SAFE_LEFT + 260, y + 75], radius=20, fill=bg_color)
        draw.text((SAFE_LEFT + 130, y + 37), text, font=font, fill=txt_color, anchor="mm")
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

def _draw_circular_timer(img: Image.Image, progress: float, center: tuple[int, int], radius: int = 90, thickness: int = 14) -> Image.Image:
    draw = ImageDraw.Draw(img, "RGBA")
    cx, cy = center
    draw.arc([cx - radius, cy - radius, cx + radius, cy + radius], start=0, end=360, fill=(60, 60, 60, 200), width=thickness)
    if progress < 0.5: t = progress / 0.5; r, g, b = int(TIMER_GREEN[0] + t * (255 - TIMER_GREEN[0])), int(TIMER_GREEN[1] + t * (200 - TIMER_GREEN[1])), int(TIMER_GREEN[2])
    else: t = (progress - 0.5) / 0.5; r, g, b = 255, int(200 - t * 155), int(TIMER_GREEN[2])
    remaining_angle = 360 * (1.0 - progress)
    if remaining_angle > 0.5: draw.arc([cx - radius, cy - radius, cx + radius, cy + radius], start=-90, end=-90 + remaining_angle, fill=(r, g, b, 255), width=thickness)
    _draw_text_with_stroke(draw, str(max(0, math.ceil(5 * (1.0 - progress)))), center, _get_font("extrabold", size=int(radius * 0.9)), WHITE, stroke_width=3)
    return img

class WatermarkEngine:
    def __init__(self, handle: str = "@Quizzaro_1") -> None:
        self._handle = handle
        self._font = _get_font("regular", size=32)
    def apply(self, img: Image.Image, frame_index: int, total_frames: int) -> Image.Image:
        t = frame_index / max(total_frames - 1, 1)
        x, y = int(SAFE_LEFT + t * (SAFE_W - 200)), int(HEIGHT * 0.08 + math.sin(t * math.pi) * HEIGHT * 0.05)
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).text((x, y), self._handle, font=self._font, fill=WATERMARK_COLOR)
        return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

def _popup_scale(frame_in_anim: int, anim_frames: int) -> float:
    return 1.0 - (1.0 - min(frame_in_anim / anim_frames, 1.0)) ** 3

def _draw_answer_reveal(img: Image.Image, answer_text: str, frame_in_reveal: int, cx: int, wrap_w: int) -> Image.Image:
    draw_img = img.copy().convert("RGBA")
    glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    font = _get_font("extrabold", 80 if len(answer_text) < 15 else 60)
    lines = _wrap_text(answer_text, font, wrap_w)
    cy = HEIGHT // 2 + 80
    for _ in range(3): _draw_multiline_centered(gd, lines, cx, cy, font, PHOSPHOR_GREEN + (120,), stroke_width=0)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=18))
    sharp_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    _draw_multiline_centered(ImageDraw.Draw(sharp_layer), lines, cx, cy, font, PHOSPHOR_GREEN + (255,), stroke_width=5)
    glow_layer.putalpha(ImageDraw.ImageDraw(glow_layer))
    return Image.alpha_composite(Image.alpha_composite(draw_img, glow_layer), sharp_layer).convert("RGB")

@dataclass
class RenderJob:
    question: QuestionObject
    bg_frames: list[np.ndarray]
    total_frames: int
    question_end_frame: int
    timer_start_frame: int
    timer_end_frame: int
    answer_reveal_frame: int
    job_dir: Path
    watermark: WatermarkEngine

def _render_frame(job: RenderJob, frame_idx: int) -> np.ndarray:
    bg = _pil_from_bgr(job.bg_frames[min(frame_idx, len(job.bg_frames) - 1)])
    img = _draw_dark_overlay(bg, alpha=155)
    q = job.question

    is_rapid = (q.template == "rapid_list")

    if is_rapid:
        q_lines = [l.strip() for l in q.question_text.split('|') if l.strip()][:5]
        a_lines = [l.strip() for l in q.correct_answer.split('|') if l.strip()][:5]
        layout_cx = WIDTH // 2
        layout_wrap = SAFE_W - 20
    elif q.template == "visual_levels":
        img = _draw_levels_sidebar(img, (len(q.question_text) + len(q.correct_answer)) % 4)
        layout_cx, layout_wrap = 670, 620
    else:
        layout_cx, layout_wrap = WIDTH // 2, SAFE_W - 20

    if frame_idx < job.timer_start_frame:
        phase_frame = frame_idx
        scale = _popup_scale(phase_frame, int(FPS * 0.35))
        alpha_val = int(255 * min(1.0, scale * 1.5))

        badge_text = "🔥 RAPID 5 QUIZ" if is_rapid else "🎮 LEVEL UP QUIZ" if q.template == "visual_levels" else q.template.replace("_", " ").upper()
        badge_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
        bd = ImageDraw.Draw(badge_img)
        bd.rounded_rectangle([layout_cx - 160, SAFE_TOP + 30, layout_cx + 160, SAFE_TOP + 80], radius=20, fill=(255, 200, 0, 220))
        bd.text((layout_cx, SAFE_TOP + 55), badge_text, font=_get_font("bold", 36), fill=(0, 0, 0), anchor="mm")
        img = Image.alpha_composite(img.convert("RGBA"), badge_img).convert("RGB")

        text_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
        td = ImageDraw.Draw(text_img)
        
        if is_rapid:
            # رسم القائمة السريعة
            list_font = _get_font("extrabold", 45)
            start_y = HEIGHT // 2 - 250
            for i, line in enumerate(q_lines):
                y = start_y + i * 110
                td.rounded_rectangle([SAFE_LEFT, y - 40, SAFE_LEFT + 400, y + 40], radius=15, fill=(0, 0, 0, int(150 * min(1.0, scale))))
                _draw_text_with_stroke(td, line, (SAFE_LEFT + 20, y), list_font, (255, 255, 255, alpha_val), anchor="lm", align="left")
        else:
            q_font = _get_font("extrabold", max(40, min(72, int(72 * scale))))
            _draw_multiline_centered(td, _wrap_text(q.question_text, q_font, layout_wrap), layout_cx, HEIGHT // 2 - 60, q_font, (255, 255, 255, alpha_val), stroke_width=5)
        
        img = Image.alpha_composite(img.convert("RGBA"), text_img).convert("RGB")

        if phase_frame > int(FPS * 0.5) and not is_rapid:
            cta_font = _get_font("regular", 32)
            cta_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
            _draw_multiline_centered(ImageDraw.Draw(cta_img), _wrap_text(q.cta_text, cta_font, layout_wrap), layout_cx, HEIGHT // 2 + 220, cta_font, (255, 230, 100, 200), stroke_width=3)
            img = Image.alpha_composite(img.convert("RGBA"), cta_img).convert("RGB")

        # الاختيارات للقوالب القديمة
        if q.template == "multiple_choice" and phase_frame > int(FPS * 0.7) and q.wrong_answers:
            all_options = [q.correct_answer] + q.wrong_answers[:3]
            random.shuffle(all_options)
            opt_start_y = HEIGHT // 2 + 120
            for i, (label, opt) in enumerate(zip(["A", "B", "C", "D"], all_options)):
                oy = opt_start_y + i * 90
                opt_bg = Image.new("RGBA", img.size, (0, 0, 0, 0))
                od = ImageDraw.Draw(opt_bg)
                od.rounded_rectangle([SAFE_LEFT, oy - 30, SAFE_RIGHT, oy + 30], radius=15, fill=(255, 255, 255, 40))
                od.text((SAFE_LEFT + 20, oy), f"{label}.  {opt}", font=_get_font("bold", 38), fill=(255, 255, 255), anchor="lm")
                img = Image.alpha_composite(img.convert("RGBA"), opt_bg).convert("RGB")

    elif frame_idx < job.timer_end_frame:
        progress = (frame_idx - job.timer_start_frame) / (job.timer_end_frame - job.timer_start_frame)
        text_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
        td = ImageDraw.Draw(text_img)
        
        if is_rapid:
            list_font = _get_font("extrabold", 45)
            start_y = HEIGHT // 2 - 250
            for i, line in enumerate(q_lines):
                y = start_y + i * 110
                td.rounded_rectangle([SAFE_LEFT, y - 40, SAFE_LEFT + 400, y + 40], radius=15, fill=(0, 0, 0, 150))
                _draw_text_with_stroke(td, line, (SAFE_LEFT + 20, y), list_font, (255, 255, 255, 255), anchor="lm", align="left")
            timer_center = (layout_cx, HEIGHT // 2 + 350)
            img = Image.alpha_composite(img.convert("RGBA"), text_img).convert("RGB")
            img = _draw_circular_timer(img.convert("RGBA"), progress, timer_center, radius=80, thickness=12).convert("RGB")
        else:
            q_font = _get_font("extrabold", 60)
            _draw_multiline_centered(td, _wrap_text(q.question_text, q_font, layout_wrap), layout_cx, HEIGHT // 2 - 180, q_font, (255, 255, 255, 180), stroke_width=5)
            img = Image.alpha_composite(img.convert("RGBA"), text_img).convert("RGB")
            img = _draw_circular_timer(img.convert("RGBA"), progress, (layout_cx, HEIGHT // 2 + 100), radius=110, thickness=18).convert("RGB")

    else:
        reveal_frame = frame_idx - job.answer_reveal_frame
        if is_rapid:
            text_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
            td = ImageDraw.Draw(text_img)
            list_font = _get_font("extrabold", 45)
            ans_font = _get_font("extrabold", 50)
            start_y = HEIGHT // 2 - 250
            for i, line in enumerate(q_lines):
                y = start_y + i * 110
                td.rounded_rectangle([SAFE_LEFT, y - 40, SAFE_LEFT + 400, y + 40], radius=15, fill=(0, 0, 0, 150))
                _draw_text_with_stroke(td, line, (SAFE_LEFT + 20, y), list_font, (255, 255, 255, 255), anchor="lm", align="left")
                if i < len(a_lines):
                    ans_clean = re.sub(r'^\d+[\.\-]\s*', '', a_lines[i]).strip()
                    _draw_text_with_stroke(td, f"👉 {ans_clean}", (SAFE_LEFT + 430, y), ans_font, PHOSPHOR_GREEN, anchor="lm", align="left")
            img = Image.alpha_composite(img.convert("RGBA"), text_img).convert("RGB")
            
            # Badge score pulse
            pulse = min(1.0, reveal_frame / 6)
            badge_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(badge_img).text((layout_cx, HEIGHT // 2 + 350), "How many did you get?", font=_get_font("bold", 40), fill=(255,220,50, int(255*pulse)), anchor="mm")
            img = Image.alpha_composite(img.convert("RGBA"), badge_img).convert("RGB")
        else:
            img = _draw_answer_reveal(img, q.correct_answer, reveal_frame, layout_cx, layout_wrap)
            badge_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
            bd = ImageDraw.Draw(badge_img)
            bd.rounded_rectangle([layout_cx - 180, HEIGHT // 2 - 200, layout_cx + 180, HEIGHT // 2 - 130], radius=25, fill=(57, 255, 20, 200))
            bd.text((layout_cx, HEIGHT // 2 - 165), "✓  CORRECT!", font=_get_font("extrabold", 52), fill=BLACK, anchor="mm")
            img = Image.alpha_composite(img.convert("RGBA"), badge_img).convert("RGB")

    img = job.watermark.apply(img, frame_idx, job.total_frames)
    return _bgr_from_pil(img)


class VideoRenderer:
    QUESTION_DISPLAY_SEC = 4.0
    TIMER_SEC = 5.0
    ANSWER_SEC = 5.0
    BASE_DURATION = QUESTION_DISPLAY_SEC + TIMER_SEC + ANSWER_SEC

    def __init__(self, pexels_key: str, pixabay_key: str, freesound_api_key: str) -> None:
        self._bg = BackgroundManager(pexels_key, pixabay_key)
        self._music = MusicEngine(freesound_api_key)
        self._watermark = WatermarkEngine()

    def render(self, question: QuestionObject, audio_engine, job_id: str) -> str:
        job_dir = RENDER_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        duration_jitter = random.uniform(-1.2, 1.5)
        extra_q_sec = max(0.0, duration_jitter)
        total_sec = self.BASE_DURATION + extra_q_sec
        q_display_sec = self.QUESTION_DISPLAY_SEC + extra_q_sec

        total_frames = int(total_sec * FPS)
        timer_start_frame = int(q_display_sec * FPS)
        timer_end_frame = timer_start_frame + int(self.TIMER_SEC * FPS)
        answer_reveal_frame = timer_end_frame

        bg_frames = self._bg.get_background_frames(total_sec, job_dir)

        # نعالج النص قبل ما الصوت يقراه (عشان ميقرأش العلامات كرموز غريبة)
        q_text_audio = question.question_text.replace(" | ", "... ")
        audio_result = audio_engine.render_question_audio(
            question_text=q_text_audio,
            cta_text=question.cta_text,
            job_id=job_id,
        )

        bgm_path = str(job_dir / "bgm.wav")
        bgm_result = self._music.get_bgm(int(total_sec * 1000), bgm_path)
        bgm_audio = AudioSegment.from_file(bgm_path) if bgm_result else AudioSegment.silent(duration=int(total_sec * 1000))

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

        render_job = RenderJob(question, bg_frames, total_frames, timer_start_frame, timer_start_frame, timer_end_frame, answer_reveal_frame, job_dir, self._watermark)
        frames_dir = job_dir / "frames"
        frames_dir.mkdir(exist_ok=True)

        for i in range(total_frames):
            cv2.imwrite(str(frames_dir / f"frame_{i:05d}.png"), _render_frame(render_job, i))

        output_path = str(job_dir / "final_short.mp4")
        self._ffmpeg_assemble(str(frames_dir), audio_path, output_path, total_sec)
        shutil.rmtree(str(frames_dir), ignore_errors=True)
        return output_path

    @staticmethod
    def _ffmpeg_assemble(frames_dir: str, audio_path: str, output_path: str, duration: float) -> None:
        cmd = [
            "ffmpeg", "-y", "-framerate", str(FPS), "-i", f"{frames_dir}/frame_%05d.png", "-i", audio_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", "-t", f"{duration:.2f}", output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0: raise RuntimeError(f"FFmpeg failed:\n{result.stderr}")
