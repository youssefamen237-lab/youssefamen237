from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Optional

import requests

from .base import AssetPick, BackgroundProviderBase

logger = logging.getLogger(__name__)


class PexelsBackgroundProvider(BackgroundProviderBase):
    key = "bg_pexels"

    def __init__(self, *, rng: random.Random, api_key: str, out_dir: Path) -> None:
        self.rng = rng
        self.api_key = api_key.strip()
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_available(self) -> bool:
        return bool(self.api_key)

    def pick(self) -> Optional[AssetPick]:
        if not self.api_key:
            return None

        headers = {"Authorization": self.api_key}
        query = self.rng.choice([
            "abstract background",
            "gradient background",
            "bokeh background",
            "minimal background",
        ])
        url = "https://api.pexels.com/v1/search"
        params = {"query": query, "per_page": 20, "orientation": "landscape"}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Pexels fetch failed: %s", e)
            return None

        photos = data.get("photos") or []
        if not photos:
            return None

        photo = self.rng.choice(photos)
        src = (photo.get("src") or {}).get("large2x") or (photo.get("src") or {}).get("large") or (photo.get("src") or {}).get("original")
        if not src:
            return None

        photo_id = str(photo.get("id") or "pexels")
        out_path = self.out_dir / f"pexels_{photo_id}.jpg"

        try:
            r = requests.get(src, timeout=30)
            r.raise_for_status()
            out_path.write_bytes(r.content)
        except Exception as e:
            logger.warning("Pexels download failed: %s", e)
            return None

        if not out_path.exists() or out_path.stat().st_size < 10_000:
            return None

        return AssetPick(path=out_path, asset_id=out_path.stem, provider_key=self.key)
