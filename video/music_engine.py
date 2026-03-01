"""
video/music_engine.py – Quizzaro Music Engine
===============================================
Downloads royalty-free background music from Freesound (CC0 licence),
cuts a random slice from each track (anti-Content-ID fingerprinting),
applies fade-in/out, and returns a pydub AudioSegment.

Enforces the 7-day no-repeat rule via AntiDuplicate.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Optional

import requests
from loguru import logger
from pydub import AudioSegment
from pydub.effects import normalize

from core.anti_duplicate import AntiDuplicate

MUSIC_CACHE_DIR = Path("data/music_cache")
MUSIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)

MUSIC_QUERIES = [
    "lofi quiz background music",
    "chill background instrumental no copyright",
    "quiz show music upbeat",
    "educational background calm music",
    "game show background loop",
    "ambient electronic background",
]


class MusicEngine:

    FREESOUND_BASE = "https://freesound.org/apiv2"

    def __init__(self, freesound_api_key: str, anti_duplicate: AntiDuplicate) -> None:
        self._api_key = freesound_api_key
        self._dup = anti_duplicate

    def _search(self, query: str, min_dur: int = 25) -> Optional[dict]:
        try:
            resp = requests.get(
                f"{self.FREESOUND_BASE}/search/text/",
                params={
                    "query": query,
                    "filter": f'duration:[{min_dur} TO 300] license:"Creative Commons 0"',
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
                if self._dup.is_music_used(sid):
                    continue
                preview = (sound.get("previews", {}).get("preview-hq-mp3") or
                           sound.get("previews", {}).get("preview-lq-mp3"))
                if preview:
                    return {"id": sid, "url": preview}
        except Exception as exc:
            logger.warning(f"[MusicEngine] Search failed: {exc}")
        return None

    def _download(self, url: str, dest: str) -> bool:
        try:
            resp = requests.get(url, timeout=40, stream=True)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            return True
        except Exception as exc:
            logger.error(f"[MusicEngine] Download failed: {exc}")
            return False

    def get_bgm(self, duration_ms: int, dest_path: str) -> Optional[AudioSegment]:
        """
        Return a trimmed, faded AudioSegment for use as background music.
        Returns None if no track can be obtained (caller must handle silence).
        """
        query = random.choice(MUSIC_QUERIES)
        meta = self._search(query)
        if not meta:
            return None

        raw_path = dest_path.replace(".wav", "_raw.mp3")
        if not self._download(meta["url"], raw_path):
            return None

        try:
            audio = AudioSegment.from_file(raw_path)
            audio = normalize(audio)

            # Cut a random slice (anti-ContentID)
            if len(audio) > duration_ms + 6000:
                max_start = len(audio) - duration_ms - 2000
                start = random.randint(0, max_start)
                audio = audio[start: start + duration_ms + 2000]

            audio = audio.fade_in(600).fade_out(1200)
            audio = audio.set_frame_rate(44100).set_channels(2)

            # Truncate to exact duration
            audio = audio[:duration_ms]

            self._dup.mark_music_used(meta["id"])
            return audio

        except Exception as exc:
            logger.error(f"[MusicEngine] Processing failed: {exc}")
            return None
