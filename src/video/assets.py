from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw

from ..utils.fs import list_files, ensure_dir, IMAGE_EXTS, AUDIO_EXTS
from ..state import add_history

log = logging.getLogger("assets")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _pick_non_recent(paths: List[Path], recent_keys: List[str]) -> Optional[Path]:
    if not paths:
        return None
    shuffled = list(paths)
    random.shuffle(shuffled)
    for p in shuffled:
        k = str(p.name)
        if k not in recent_keys:
            return p
    return random.choice(paths)


def pick_local_image(cfg: Dict[str, Any], state: Dict[str, Any]) -> Optional[Path]:
    images_dir = Path(cfg["assets"]["images_dir"])
    imgs = list_files(images_dir, IMAGE_EXTS)
    recent_days = int(cfg["safety"]["no_repeat_background_days"])
    hist = state.get("background_history") if isinstance(state.get("background_history"), list) else []
    recent = [str(it.get("key")) for it in hist if isinstance(it, dict) and it.get("key")]
    chosen = _pick_non_recent(imgs, recent)
    if not chosen:
        return None
    add_history(state, "background_history", {"ts": _now_iso(), "key": chosen.name}, keep_days=recent_days)
    return chosen


def pick_local_music(cfg: Dict[str, Any], state: Dict[str, Any]) -> Optional[Path]:
    music_dir = Path(cfg["assets"]["music_dir"])
    tracks = list_files(music_dir, AUDIO_EXTS)
    if not tracks:
        return None
    recent_days = int(cfg["safety"]["no_repeat_music_days"])
    hist = state.get("music_history") if isinstance(state.get("music_history"), list) else []
    recent = [str(it.get("key")) for it in hist if isinstance(it, dict) and it.get("key")]
    chosen = _pick_non_recent(tracks, recent)
    if not chosen:
        return None
    add_history(state, "music_history", {"ts": _now_iso(), "key": chosen.name}, keep_days=recent_days)
    return chosen


def _download(url: str, out_path: Path) -> Optional[Path]:
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        out_path.write_bytes(r.content)
        return out_path
    except Exception as e:
        log.warning("download failed: %s", e)
        return None


def _pexels_random(cfg: Dict[str, Any]) -> Optional[str]:
    key_env = cfg["assets"].get("pexels_api_key_env", "PEXELS_API_KEY")
    key = os.getenv(str(key_env), "")
    if not key:
        return None
    headers = {"Authorization": key}
    try:
        r = requests.get("https://api.pexels.com/v1/curated", headers=headers, params={"per_page": 30}, timeout=30)
        r.raise_for_status()
        data = r.json()
        photos = data.get("photos")
        if not isinstance(photos, list) or not photos:
            return None
        photo = random.choice(photos)
        src = photo.get("src") if isinstance(photo, dict) else None
        if not isinstance(src, dict):
            return None
        return src.get("large2x") or src.get("large") or src.get("original")
    except Exception as e:
        log.warning("pexels fetch failed: %s", e)
        return None


def _pixabay_random(cfg: Dict[str, Any]) -> Optional[str]:
    key_env = cfg["assets"].get("pixabay_api_key_env", "PIXABAY_API_KEY")
    key = os.getenv(str(key_env), "")
    if not key:
        return None
    try:
        r = requests.get(
            "https://pixabay.com/api/",
            params={"key": key, "image_type": "photo", "per_page": 50, "safesearch": "true"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        hits = data.get("hits")
        if not isinstance(hits, list) or not hits:
            return None
        hit = random.choice(hits)
        if not isinstance(hit, dict):
            return None
        return hit.get("largeImageURL") or hit.get("webformatURL")
    except Exception as e:
        log.warning("pixabay fetch failed: %s", e)
        return None


def _unsplash_random(cfg: Dict[str, Any]) -> Optional[str]:
    key_env = cfg["assets"].get("unsplash_access_key_env", "UNSPLASH_ACCESS_KEY")
    key = os.getenv(str(key_env), "")
    if not key:
        return None
    try:
        r = requests.get(
            "https://api.unsplash.com/photos/random",
            headers={"Authorization": f"Client-ID {key}"},
            params={"orientation": "portrait"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        urls = data.get("urls")
        if not isinstance(urls, dict):
            return None
        return urls.get("regular") or urls.get("full")
    except Exception as e:
        log.warning("unsplash fetch failed: %s", e)
        return None


def generate_fallback_background(width: int, height: int, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    # simple gradient stripes
    stripes = 14
    for i in range(stripes):
        y0 = int(i * height / stripes)
        y1 = int((i + 1) * height / stripes)
        col = (random.randint(10, 70), random.randint(10, 70), random.randint(10, 70))
        draw.rectangle([0, y0, width, y1], fill=col)
    # add random circles
    for _ in range(30):
        r = random.randint(30, 160)
        x = random.randint(-r, width + r)
        y = random.randint(-r, height + r)
        col = (random.randint(60, 200), random.randint(60, 200), random.randint(60, 200))
        draw.ellipse([x - r, y - r, x + r, y + r], outline=col, width=6)
    img.save(out_path, format="PNG")
    return out_path


def pick_background(cfg: Dict[str, Any], state: Dict[str, Any], *, width: int, height: int) -> Path:
    tmp_dir = ensure_dir(cfg["assets"]["temp_dir"])
    local = pick_local_image(cfg, state)
    if local:
        return local

    allow_remote = bool(cfg["assets"].get("allow_remote_image_fallback", True))
    if allow_remote:
        sources = cfg["assets"].get("remote_image_sources") or []
        for src in sources:
            url: Optional[str] = None
            if src == "pexels":
                url = _pexels_random(cfg)
            elif src == "pixabay":
                url = _pixabay_random(cfg)
            elif src == "unsplash":
                url = _unsplash_random(cfg)
            if not url:
                continue
            out = tmp_dir / f"bg_{int(datetime.now(timezone.utc).timestamp())}_{random.randint(1000,9999)}.jpg"
            dl = _download(url, out)
            if dl:
                recent_days = int(cfg["safety"]["no_repeat_background_days"])
                add_history(state, "background_history", {"ts": _now_iso(), "key": dl.name, "remote": True}, keep_days=recent_days)
                return dl

    # Generated fallback
    out = tmp_dir / f"bg_gen_{int(datetime.now(timezone.utc).timestamp())}_{random.randint(1000,9999)}.png"
    recent_days = int(cfg["safety"]["no_repeat_background_days"])
    add_history(state, "background_history", {"ts": _now_iso(), "key": out.name, "generated": True}, keep_days=recent_days)
    return generate_fallback_background(width, height, out)
