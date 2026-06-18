"""
cascade/images/pexels_photo_provider.py

Required GitHub Secret: PEXELS_API_KEY
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

_SEARCH_URL = "https://api.pexels.com/v1/search"
_MIN_FILE_BYTES = 50_000


class PexelsPhotoProvider(BaseProvider):
    provider_name = "pexels_photo"
    is_free_tier = False
    cascade_category = "images"

    def is_available(self) -> bool:
        return self.env_present("PEXELS_API_KEY")

    def execute(self, **kwargs: Any) -> ProviderResult:
        query: str = kwargs.get("query", "").strip()
        download_dir: str = kwargs.get("download_dir", "/tmp/yta_images")
        orientation: str = kwargs.get("orientation", "landscape")
        min_width: int = int(kwargs.get("min_width", 1280))

        if not query:
            return ProviderResult.failure(self.provider_name, "Empty search query.")

        headers = {"Authorization": os.environ["PEXELS_API_KEY"]}

        try:
            resp = requests.get(
                _SEARCH_URL,
                headers=headers,
                params={
                    "query": query,
                    "per_page": 10,
                    "orientation": orientation.lower(),
                    "size": "large",
                },
                timeout=20,
            )
            if resp.status_code == 429:
                return ProviderResult.failure(self.provider_name, "Pexels photo rate limit.")
            resp.raise_for_status()
        except requests.RequestException as exc:
            return ProviderResult.failure(
                self.provider_name, f"Pexels photo search failed: {exc}"
            )

        photos: List[Dict] = resp.json().get("photos", [])
        if not photos:
            return ProviderResult.failure(
                self.provider_name, f"No Pexels photos for: {query!r}"
            )

        photo = self._select_best(photos, min_width)
        if photo is None:
            return ProviderResult.failure(
                self.provider_name, "No Pexels photo meets width requirement."
            )

        src: Dict = photo.get("src", {})
        download_url = src.get("original") or src.get("large2x") or src.get("large")
        if not download_url:
            return ProviderResult.failure(self.provider_name, "Pexels photo has no URL.")

        source_id = str(photo.get("id", "unknown"))
        local_path = str(Path(download_dir) / f"pexels_{source_id}.jpg")

        try:
            file_bytes = _download_image(download_url, local_path)
        except Exception as exc:
            return ProviderResult.failure(
                self.provider_name, f"Pexels photo download failed: {exc}"
            )

        if file_bytes < _MIN_FILE_BYTES:
            Path(local_path).unlink(missing_ok=True)
            return ProviderResult.failure(
                self.provider_name, f"Pexels image too small ({file_bytes} bytes)."
            )

        data: Dict[str, Any] = {
            "local_path": local_path,
            "source_url": download_url,
            "provider_source_id": source_id,
            "width": photo.get("width", 0),
            "height": photo.get("height", 0),
            "file_size_bytes": file_bytes,
            "provider": self.provider_name,
            "license": "royalty_free",
            "is_ai_generated": False,
        }
        logger.info("pexels_photo_downloaded", query=query, source_id=source_id)
        return ProviderResult(
            success=True, data=data,
            provider_used=self.provider_name, metadata={"query": query},
        )

    @staticmethod
    def _select_best(photos: List[Dict], min_width: int) -> Optional[Dict]:
        candidates = [p for p in photos if p.get("width", 0) >= min_width]
        if not candidates:
            candidates = photos
        return max(candidates, key=lambda p: p.get("width", 0) * p.get("height", 0)) if candidates else None


def _download_image(url: str, dest_path: str, timeout: int = 60) -> int:
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
