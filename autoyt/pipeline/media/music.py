\
from __future__ import annotations

import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from autoyt.utils.fs import ensure_dir
from autoyt.utils.logging_utils import get_logger

log = get_logger("autoyt.music")


@dataclass
class MusicAsset:
    path: Path
    asset_id: str
    source: str  # local|freesound|none
    license: Optional[str] = None
    attribution: Optional[str] = None


def _list_local_audio(music_dir: Path) -> List[Path]:
    if not music_dir.exists():
        return []
    exts = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
    files = [p for p in music_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
    files.sort()
    return files


def _download(url: str, out_path: Path, timeout_s: int = 60) -> None:
    ensure_dir(out_path.parent)
    r = requests.get(url, timeout=timeout_s, headers={"User-Agent": "autoyt/1.0"})
    r.raise_for_status()
    out_path.write_bytes(r.content)


def _freesound_search(query: str, cache_dir: Path) -> Optional[MusicAsset]:
    token = os.environ.get("FREESOUND_API", "") or os.environ.get("FREESOUND_ID", "")
    if not token:
        return None
    url = "https://freesound.org/apiv2/search/text/"
    params = {
        "query": query,
        "filter": 'license:"Creative Commons 0"',
        "fields": "id,name,license,previews,duration",
        "sort": "rating_desc",
        "page_size": 25,
        "token": token,
    }
    r = requests.get(url, params=params, timeout=30, headers={"User-Agent": "autoyt/1.0"})
    r.raise_for_status()
    data = r.json() or {}
    results = data.get("results") or []
    if not results:
        return None

    pick = random.choice(results)
    sid = str(pick.get("id") or "")
    previews = pick.get("previews") or {}
    src = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3") or ""
    if not sid or not src:
        return None
    out = cache_dir / f"freesound_{sid}.mp3"
    if not out.exists():
        _download(src, out)
    return MusicAsset(path=out, asset_id=f"freesound:{sid}", source="freesound", license=str(pick.get("license") or ""))


def pick_music(
    repo_root: Path,
    cfg_state: Dict[str, Any],
    rng: random.Random,
    allow_external: bool = True,
) -> Optional[MusicAsset]:
    """
    Returns a MusicAsset or None. Never raises.
    """
    cfg_state.setdefault("recent_music_ids", [])
    music_dir = repo_root / "assets" / "music"
    cache_dir = repo_root / ".cache" / "music"
    ensure_dir(cache_dir)

    local = _list_local_audio(music_dir)
    if local:
        recent = set(cfg_state["recent_music_ids"][-20:])
        candidates = [p for p in local if p.name not in recent] or local
        p = rng.choice(candidates)
        cfg_state["recent_music_ids"].append(p.name)
        cfg_state["recent_music_ids"] = cfg_state["recent_music_ids"][-100:]
        return MusicAsset(path=p, asset_id=f"local:{p.name}", source="local")

    if not allow_external:
        return None

    # external fallback: Freesound CC0 previews
    try:
        q = rng.choice(["lofi", "ambient", "soft beat", "chill"])
        asset = _freesound_search(q, cache_dir)
        if asset:
            cfg_state["recent_music_ids"].append(asset.asset_id)
            cfg_state["recent_music_ids"] = cfg_state["recent_music_ids"][-100:]
            return asset
    except Exception as e:
        log.warning(f"Freesound failed: {e}")

    return None
