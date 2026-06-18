"""
intelligence/music_selector.py
"""
from __future__ import annotations
import os, tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
import requests, structlog
from storage.supabase_client import get_db
from storage.r2_client import R2Paths, get_r2

logger = structlog.get_logger(__name__)

# Category → preferred mood, per channel constitution
_CATEGORY_MOOD: Dict[str, str] = {
    "ocean":   "mysterious",
    "space":   "epic",
    "animals": "tense",
    "nature":  "documentary",
    "birds":   "calm",
    "insects": "tense",
}

_MIN_FILE_BYTES = 50_000


@dataclass
class MusicSelection:
    local_path: Optional[str]
    track_id:   Optional[str]
    track_name: Optional[str]
    category:   str
    mood:       Optional[str]


class MusicSelector:

    def __init__(self) -> None:
        self._db = get_db()
        self._r2 = get_r2()

    # ── Public API ────────────────────────────────────────────────────────────

    def select_track(
        self,
        category:   str,
        download_dir: Optional[str] = None,
    ) -> MusicSelection:
        """
        Return a MusicSelection with a local_path ready for FFmpeg.
        local_path is None if no track could be obtained — callers (the
        assembler) must treat this as "no background music" and continue.
        """
        mood = _CATEGORY_MOOD.get(category, "documentary")

        if download_dir is None:
            download_dir = tempfile.mkdtemp(prefix="yta_music_")
        os.makedirs(download_dir, exist_ok=True)

        row = self._safe_get_track(category, mood)
        if row is None:
            logger.info("music_none_available", category=category, mood=mood)
            return MusicSelection(None, None, None, category, mood)

        track_id   = row.get("track_id")
        track_name = row.get("track_name")
        local_path = os.path.join(download_dir, f"music_{track_id}.mp3")

        # 1) Already cached in R2
        r2_path = row.get("r2_path")
        if row.get("is_downloaded") and r2_path:
            try:
                self._r2.download_file(r2_path, local_path)
                if Path(local_path).stat().st_size >= _MIN_FILE_BYTES:
                    return MusicSelection(local_path, track_id, track_name, category, mood)
            except Exception as exc:
                logger.debug("music_r2_fetch_failed", track_id=track_id, error=str(exc)[:80])

        # 2) Download from source_url and cache to R2
        source_url = row.get("source_url")
        if source_url:
            try:
                size = _download(source_url, local_path)
                if size >= _MIN_FILE_BYTES:
                    self._cache_to_r2(track_id, local_path)
                    return MusicSelection(local_path, track_id, track_name, category, mood)
                Path(local_path).unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("music_source_download_failed", track_id=track_id, error=str(exc)[:80])

        logger.info("music_unavailable_no_audio_bed", category=category, track_id=track_id)
        return MusicSelection(None, track_id, track_name, category, mood)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _safe_get_track(self, category: str, mood: str) -> Optional[Dict]:
        try:
            return self._db.get_music_track(category, mood)
        except Exception as exc:
            logger.debug("music_db_fetch_failed", category=category, error=str(exc)[:80])
            return None

    def _cache_to_r2(self, track_id: str, local_path: str) -> None:
        try:
            r2_key = R2Paths.music_track(f"{track_id}.mp3")
            self._r2.upload_file(local_path, r2_key, content_type="audio/mpeg")
            self._db.mark_music_downloaded(track_id, r2_key)
        except Exception as exc:
            logger.debug("music_r2_cache_failed", track_id=track_id, error=str(exc)[:80])


def _download(url: str, dest_path: str, timeout: int = 60) -> int:
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as fh:
            for chunk in r.iter_content(chunk_size=16_384):
                if chunk:
                    fh.write(chunk)
                    total += len(chunk)
    return total


_instance: Optional[MusicSelector] = None

def get_music_selector() -> MusicSelector:
    global _instance
    if _instance is None:
        _instance = MusicSelector()
    return _instance
