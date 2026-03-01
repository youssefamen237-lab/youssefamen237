"""
video/background_manager.py – Quizzaro Background Manager
===========================================================
Downloads a fresh B-roll video clip per Short from Pexels (primary)
or Pixabay (fallback), applies Gaussian blur, extracts exactly the
frames needed for the video duration, and enforces the 10-day no-repeat rule.

If both APIs fail, returns a procedurally generated gradient frame sequence.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import requests
from loguru import logger

from core.anti_duplicate import AntiDuplicate

BG_CACHE_DIR = Path("data/bg_cache")
BG_CACHE_DIR.mkdir(parents=True, exist_ok=True)

WIDTH = 1080
HEIGHT = 1920
FPS = 30

BG_QUERIES = [
    "abstract motion", "particles bokeh", "nature timelapse", "city night lights",
    "galaxy stars space", "ocean waves", "neon lights", "fire embers glow",
    "forest fog mist", "geometric shapes loop", "futuristic tunnel",
    "aurora borealis", "rainy window blur", "underwater bubbles",
]


class BackgroundManager:

    PEXELS_BASE = "https://api.pexels.com/videos/search"
    PIXABAY_BASE = "https://pixabay.com/api/videos/"

    def __init__(self, pexels_key: str, pixabay_key: str, anti_duplicate: AntiDuplicate) -> None:
        self._pexels_key = pexels_key
        self._pixabay_key = pixabay_key
        self._dup = anti_duplicate

    def _pexels_search(self, query: str) -> Optional[dict]:
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
                vid_id = f"pexels_{v['id']}"
                if self._dup.is_background_used(vid_id):
                    continue
                files = sorted(v.get("video_files", []), key=lambda f: f.get("height", 0), reverse=True)
                for f in files:
                    if f.get("width", 1) <= f.get("height", 0):  # portrait only
                        return {"id": vid_id, "url": f["link"]}
        except Exception as exc:
            logger.warning(f"[BgManager] Pexels failed: {exc}")
        return None

    def _pixabay_search(self, query: str) -> Optional[dict]:
        try:
            resp = requests.get(
                self.PIXABAY_BASE,
                params={"key": self._pixabay_key, "q": query,
                        "video_type": "animation", "per_page": 15, "safesearch": "true"},
                timeout=15,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
            random.shuffle(hits)
            for h in hits:
                vid_id = f"pixabay_{h['id']}"
                if self._dup.is_background_used(vid_id):
                    continue
                for q in ("large", "medium", "small", "tiny"):
                    url = h.get("videos", {}).get(q, {}).get("url")
                    if url:
                        return {"id": vid_id, "url": url}
        except Exception as exc:
            logger.warning(f"[BgManager] Pixabay failed: {exc}")
        return None

    def _download(self, url: str, dest: str) -> bool:
        try:
            resp = requests.get(url, timeout=60, stream=True)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(65536):
                    f.write(chunk)
            return True
        except Exception as exc:
            logger.error(f"[BgManager] Download error: {exc}")
            return False

    @staticmethod
    def _extract_and_blur(video_path: str, needed_frames: int) -> list[np.ndarray]:
        cap = cv2.VideoCapture(video_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30

        max_start = max(0, total - needed_frames - 1)
        start = random.randint(0, max_start) if max_start > 0 else 0
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)

        raw: list[np.ndarray] = []
        for _ in range(needed_frames + 60):
            ret, frame = cap.read()
            if not ret:
                break
            raw.append(frame)
        cap.release()

        if not raw:
            return []

        indices = np.linspace(0, len(raw) - 1, needed_frames, dtype=int)
        frames: list[np.ndarray] = []
        for idx in indices:
            frame = raw[idx]
            h, w = frame.shape[:2]
            scale = max(WIDTH / w, HEIGHT / h)
            nw, nh = int(w * scale), int(h * scale)
            resized = cv2.resize(frame, (nw, nh))
            x, y = (nw - WIDTH) // 2, (nh - HEIGHT) // 2
            cropped = resized[y:y + HEIGHT, x:x + WIDTH]
            blurred = cv2.GaussianBlur(cropped, (51, 51), 0)
            frames.append(blurred)
        return frames

    @staticmethod
    def _gradient_frames(needed: int) -> list[np.ndarray]:
        base = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        for y in range(HEIGHT):
            t = y / HEIGHT
            base[y, :] = [int(18 + t * 10), int(8 + t * 18), int(38 + t * 55)]
        return [base.copy() for _ in range(needed)]

    def get_background_frames(self, duration_sec: float, job_dir: Path) -> list[np.ndarray]:
        needed = int(duration_sec * FPS)
        query = random.choice(BG_QUERIES)
        dest = str(job_dir / "background.mp4")

        meta = self._pexels_search(query) or self._pixabay_search(query)
        if meta and self._download(meta["url"], dest):
            frames = self._extract_and_blur(dest, needed)
            if frames:
                self._dup.mark_background_used(meta["id"])
                return frames
            logger.warning("[BgManager] Frame extraction empty. Using gradient.")
        else:
            logger.warning("[BgManager] No video obtained. Using gradient.")

        return self._gradient_frames(needed)
