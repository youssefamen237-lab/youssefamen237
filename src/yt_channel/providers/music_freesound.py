from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Optional

import requests

from .base import AudioPick, MusicProviderBase

logger = logging.getLogger(__name__)


class FreesoundMusicProvider(MusicProviderBase):
    key = "music_freesound"

    def __init__(self, *, rng: random.Random, token: str, out_dir: Path) -> None:
        self.rng = rng
        self.token = token.strip()
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_available(self) -> bool:
        return bool(self.token)

    def pick(self, *, duration_seconds: float) -> Optional[AudioPick]:
        if not self.token:
            return None

        headers = {"Authorization": f"Token {self.token}"}
        query = self.rng.choice([
            "ambient loop",
            "lofi loop",
            "soft beat loop",
            "chill pad loop",
        ])

        # Prefer CC0 to avoid claims.
        # Freesound filter syntax: https://freesound.org/docs/api/resources_apiv2.html
        duration_min = 20
        duration_max = 180
        filter_q = f'license:"Creative Commons 0" duration:[{duration_min} TO {duration_max}]'

        url = "https://freesound.org/apiv2/search/text/"
        params = {
            "query": query,
            "filter": filter_q,
            "fields": "id,name,previews,duration,license",
            "page_size": 20,
        }

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Freesound search failed: %s", e)
            return None

        results = data.get("results") or []
        if not results:
            return None

        sound = self.rng.choice(results)
        sid = str(sound.get("id") or "")
        name = str(sound.get("name") or "freesound")
        if not sid:
            return None

        # Prefer MP3 preview to keep downloads light.
        previews = sound.get("previews") or {}
        preview_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
        if not preview_url:
            return None

        safe_name = "".join(ch for ch in name if ch.isalnum() or ch in "-_ ").strip().replace(" ", "_")
        out_path = self.out_dir / f"freesound_{sid}_{safe_name}.mp3"

        try:
            r = requests.get(preview_url, timeout=30)
            r.raise_for_status()
            out_path.write_bytes(r.content)
        except Exception as e:
            logger.warning("Freesound download failed: %s", e)
            return None

        if not out_path.exists() or out_path.stat().st_size < 10_000:
            return None

        return AudioPick(path=out_path, asset_id=out_path.stem, provider_key=self.key)
