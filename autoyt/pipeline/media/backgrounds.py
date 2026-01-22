\
from __future__ import annotations

import hashlib
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image

from autoyt.utils.fs import ensure_dir
from autoyt.utils.logging_utils import get_logger

log = get_logger("autoyt.backgrounds")


@dataclass
class BackgroundAsset:
    path: Path
    asset_id: str
    source: str  # local|pexels|pixabay|unsplash|generated


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()[:18]


def _list_local_images(bg_dir: Path) -> List[Path]:
    if not bg_dir.exists():
        return []
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    files = [p for p in bg_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
    files.sort()
    return files


def _download(url: str, out_path: Path, timeout_s: int = 30) -> None:
    ensure_dir(out_path.parent)
    r = requests.get(url, timeout=timeout_s, headers={"User-Agent": "autoyt/1.0"})
    r.raise_for_status()
    out_path.write_bytes(r.content)


def _pexels_search(query: str, cache_dir: Path) -> Optional[BackgroundAsset]:
    key = os.environ.get("PEXELS_API_KEY", "")
    if not key:
        return None
    url = "https://api.pexels.com/v1/search"
    params = {"query": query, "orientation": "portrait", "per_page": 30}
    headers = {"Authorization": key, "User-Agent": "autoyt/1.0"}
    r = requests.get(url, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json() or {}
    photos = data.get("photos") or []
    if not photos:
        return None
    pick = random.choice(photos)
    src = (pick.get("src") or {}).get("large2x") or (pick.get("src") or {}).get("large") or ""
    if not src:
        return None
    pid = str(pick.get("id") or _hash(src))
    out = cache_dir / f"pexels_{pid}.jpg"
    if not out.exists():
        _download(src, out)
    return BackgroundAsset(path=out, asset_id=f"pexels:{pid}", source="pexels")


def _pixabay_search(query: str, cache_dir: Path) -> Optional[BackgroundAsset]:
    key = os.environ.get("PIXABAY_API_KEY", "")
    if not key:
        return None
    url = "https://pixabay.com/api/"
    params = {"key": key, "q": query, "orientation": "vertical", "image_type": "photo", "safesearch": "true", "per_page": 50}
    r = requests.get(url, params=params, timeout=30, headers={"User-Agent": "autoyt/1.0"})
    r.raise_for_status()
    data = r.json() or {}
    hits = data.get("hits") or []
    if not hits:
        return None
    pick = random.choice(hits)
    src = pick.get("largeImageURL") or pick.get("webformatURL") or ""
    if not src:
        return None
    pid = str(pick.get("id") or _hash(src))
    out = cache_dir / f"pixabay_{pid}.jpg"
    if not out.exists():
        _download(src, out)
    return BackgroundAsset(path=out, asset_id=f"pixabay:{pid}", source="pixabay")


def _unsplash_search(query: str, cache_dir: Path) -> Optional[BackgroundAsset]:
    key = os.environ.get("UNSPLASH_ACCESS_KEY", "") or os.environ.get("UNSPLASH_ID", "")
    if not key:
        return None
    url = "https://api.unsplash.com/search/photos"
    params = {"query": query, "orientation": "portrait", "per_page": 30, "client_id": key}
    r = requests.get(url, params=params, timeout=30, headers={"User-Agent": "autoyt/1.0"})
    r.raise_for_status()
    data = r.json() or {}
    results = data.get("results") or []
    if not results:
        return None
    pick = random.choice(results)
    src = (pick.get("urls") or {}).get("regular") or (pick.get("urls") or {}).get("raw") or ""
    if not src:
        return None
    pid = str(pick.get("id") or _hash(src))
    out = cache_dir / f"unsplash_{pid}.jpg"
    if not out.exists():
        _download(src, out)
    return BackgroundAsset(path=out, asset_id=f"unsplash:{pid}", source="unsplash")


def _generated_gradient(cache_dir: Path, width: int, height: int) -> BackgroundAsset:
    ensure_dir(cache_dir)
    pid = _hash(f"gradient_{width}x{height}_{random.random()}")
    out = cache_dir / f"gen_{pid}.jpg"
    # simple gradient
    img = Image.new("RGB", (width, height))
    for y in range(height):
        v = int(255 * (y / max(1, height - 1)))
        for x in range(width):
            u = int(255 * (x / max(1, width - 1)))
            img.putpixel((x, y), (u, v, 255 - u // 2))
    img.save(out, quality=90)
    return BackgroundAsset(path=out, asset_id=f"gen:{pid}", source="generated")


def pick_background(
    repo_root: Path,
    topic: str,
    cfg_state: Dict[str, Any],
    width: int,
    height: int,
    rng: random.Random,
) -> BackgroundAsset:
    local_dir = repo_root / "assets" / "backgrounds"
    cache_dir = repo_root / ".cache" / "backgrounds"
    ensure_dir(cache_dir)

    cfg_state.setdefault("recent_background_ids", [])

    # 1) Local
    local_files = _list_local_images(local_dir)
    if local_files:
        # Avoid repeating the same file too often
        ids = [p.name for p in local_files]
        recent = set(cfg_state["recent_background_ids"][-20:])
        candidates = [p for p in local_files if p.name not in recent] or local_files
        p = rng.choice(candidates)
        asset = BackgroundAsset(path=p, asset_id=f"local:{p.name}", source="local")
        cfg_state["recent_background_ids"].append(p.name)
        cfg_state["recent_background_ids"] = cfg_state["recent_background_ids"][-100:]
        return asset

    # 2) External
    qmap = {
        "capitals": "abstract gradient",
        "flags": "abstract texture",
        "continents": "minimal abstract",
        "football": "stadium lights background",
        "geography": "travel abstract background",
    }
    query = qmap.get(topic, "abstract background")

    providers = [_pexels_search, _pixabay_search, _unsplash_search]
    rng.shuffle(providers)

    for fn in providers:
        try:
            asset = fn(query, cache_dir)
            if asset:
                cfg_state["recent_background_ids"].append(asset.asset_id)
                cfg_state["recent_background_ids"] = cfg_state["recent_background_ids"][-100:]
                return asset
        except Exception as e:
            log.warning(f"Background provider {fn.__name__} failed: {e}")

    # 3) Generated
    asset = _generated_gradient(cache_dir, width=width, height=height)
    cfg_state["recent_background_ids"].append(asset.asset_id)
    cfg_state["recent_background_ids"] = cfg_state["recent_background_ids"][-100:]
    return asset
