"""
audio/sfx_manager.py – Quizzaro SFX Manager
=============================================
Downloads and caches three sound effects from Freesound.org (CC0 licence):

  tick_tock   — 5-second countdown sound (synced to circular timer)
  ding        — correct-answer reveal chime
  whoosh      — transition swoosh layered with the ding

Files are downloaded once and cached in data/sfx_cache/.
On every call the manager returns a pydub AudioSegment ready to be
mixed into the final video audio track by AudioEngine.mix_final_audio().

If Freesound is unreachable, the manager returns silence so the pipeline
never crashes — the video is still uploaded, just without that SFX.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Optional

import requests
from loguru import logger
from pydub import AudioSegment
from pydub.effects import normalize

SFX_CACHE_DIR = Path("data/sfx_cache")
SFX_CACHE_DIR.mkdir(parents=True, exist_ok=True)

FREESOUND_BASE = "https://freesound.org/apiv2"

SFX_QUERIES: dict[str, str] = {
    "tick_tock": "tick tock countdown clock timer",
    "ding":      "correct answer bell ding chime short",
    "whoosh":    "whoosh swoosh transition reveal",
}

SAMPLE_RATE = 44100
CHANNELS = 2


class SFXManager:

    def __init__(self, freesound_api_key: str, freesound_client_id: str = "") -> None:
        self._api_key = freesound_api_key
        self._cache: dict[str, str] = {}
        self._preload()

    # ── Freesound search + download ────────────────────────────────────────

    def _search(self, query: str, max_dur: float = 12.0) -> Optional[dict]:
        try:
            resp = requests.get(
                f"{FREESOUND_BASE}/search/text/",
                params={
                    "query": query,
                    "filter": f'duration:[0.3 TO {max_dur}] license:"Creative Commons 0"',
                    "fields": "id,name,previews,duration",
                    "page_size": 15,
                    "token": self._api_key,
                },
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                return random.choice(results[:6])
        except Exception as exc:
            logger.warning(f"[SFX] Search failed for '{query}': {exc}")
        return None

    def _download(self, sound: dict, dest: str) -> bool:
        previews = sound.get("previews", {})
        url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
        if not url:
            return False
        try:
            resp = requests.get(url, timeout=30, stream=True)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            return True
        except Exception as exc:
            logger.warning(f"[SFX] Download failed: {exc}")
            return False

    def _preload(self) -> None:
        for sfx_type, query in SFX_QUERIES.items():
            cache_file = SFX_CACHE_DIR / f"{sfx_type}.mp3"
            if cache_file.exists():
                self._cache[sfx_type] = str(cache_file)
                logger.debug(f"[SFX] Cache hit: {sfx_type}")
                continue

            logger.info(f"[SFX] Downloading '{sfx_type}' …")
            sound = self._search(query)
            if sound and self._download(sound, str(cache_file)):
                self._cache[sfx_type] = str(cache_file)
                logger.success(f"[SFX] Cached: {sfx_type}")
            else:
                logger.warning(f"[SFX] Could not cache '{sfx_type}'. Will use silence.")

    # ── Public AudioSegment accessors ──────────────────────────────────────

    def _load(self, sfx_type: str, duration_ms: Optional[int] = None) -> AudioSegment:
        path = self._cache.get(sfx_type)
        if not path or not Path(path).exists():
            logger.warning(f"[SFX] '{sfx_type}' not in cache. Returning silence.")
            return AudioSegment.silent(duration=duration_ms or 1000)
        try:
            seg = AudioSegment.from_file(path)
            seg = normalize(seg).set_frame_rate(SAMPLE_RATE).set_channels(CHANNELS)
            if duration_ms:
                loops = (duration_ms // len(seg)) + 1
                seg = (seg * loops)[:duration_ms]
            return seg
        except Exception as exc:
            logger.error(f"[SFX] Load error for '{sfx_type}': {exc}")
            return AudioSegment.silent(duration=duration_ms or 1000)

    def get_tick_tock(self, duration_ms: int = 5000) -> AudioSegment:
        """Return tick-tock SFX looped to *duration_ms* milliseconds."""
        return self._load("tick_tock", duration_ms=duration_ms)

    def get_ding(self) -> AudioSegment:
        """Return correct-answer ding chime."""
        return self._load("ding")

    def get_whoosh(self) -> AudioSegment:
        """Return reveal whoosh SFX."""
        return self._load("whoosh")

    def get_answer_sfx(self) -> AudioSegment:
        """Return ding + whoosh overlaid for the answer reveal moment."""
        ding = self.get_ding() + 2      # +2 dB boost
        whoosh = self.get_whoosh()
        combined = ding.overlay(whoosh)
        return normalize(combined)
