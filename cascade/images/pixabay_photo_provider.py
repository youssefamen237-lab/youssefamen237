"""
cascade/images/pixabay_photo_provider.py

Required GitHub Secret: PIXABAY_API_KEY
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

_SEARCH_URL = "https://pixabay.com/api/"
_MIN_FILE_BYTES = 50_000


class PixabayPhotoProvider(BaseProvider):
    provider_name = "pixabay_photo"
    is_free_tier = False
    cascade_category = "images"

    def is_available(self) -> bool:
        return self.env_present("PIXABAY_API_KEY")

    def execute(self, **kwargs: Any) -> ProviderResult:
        query: str = kwargs.get("query", "").strip()
        download_dir: str = kwargs.get("download_dir", "/tmp/yta_images")
        orientation: str = kwargs.get("orientation", "horizontal")
        min_width: int = int(kwargs.get("min_width", 1280))

        if not query:
            return ProviderResult.failure(self.provider_name, "Empty search query.")

        # Pixabay orientation: "horizontal" or "vertical"
        pix_orient = "vertical" if orientation.lower() == "portrait" else "horizontal"

        try:
            resp = requests.get(
                _SEARCH_URL,
                params={
                    "key": os.environ["PIXABAY_API_KEY"],
                    "q": query,
                    "per_page": 10,
                    "image_type": "photo",
                    "orientation": pix_orient,
                    "min_width": min_width,
                    "safesearch": "true",
                    "order": "popular",
                },
                timeout=20,
            )
            if resp.status_code == 429:
                return ProviderResult.failure(self.provider_name, "Pixabay rate limit.")
            resp.raise_for_status()
        except requests.RequestException as exc:
            return ProviderResult.failure(
                self.provider_name, f"Pixabay photo search failed: {exc}"
            )

        hits: List[Dict] = resp.json().get("hits", [])
        if not hits:
            return ProviderResult.failure(
                self.provider_name, f"No Pixabay photos for: {query!r}"
            )

        # Best = most downloads among hits with sufficient width
        candidates = [h for h in hits if h.get("imageWidth", 0) >= min_width]
        if not candidates:
            candidates = hits
        photo = max(candidates, key=lambda h: h.get("downloads", 0))

        download_url = (
            photo.get("largeImageURL")
            or photo.get("fullHDURL")
            or photo.get("webformatURL")
        )
        if not download_url:
            return ProviderResult.failure(self.provider_name, "No Pixabay image URL.")

        source_id = str(photo.get("id", "unknown"))
        local_path = str(Path(download_dir) / f"pixabay_{source_id}.jpg")

        try:
            file_bytes = _download_image(download_url, local_path)
        except Exception as exc:
            return ProviderResult.failure(
                self.provider_name, f"Pixabay photo download failed: {exc}"
            )

        if file_bytes < _MIN_FILE_BYTES:
            Path(local_path).unlink(missing_ok=True)
            return ProviderResult.failure(
                self.provider_name, f"Pixabay image too small ({file_bytes} bytes)."
            )

        data: Dict[str, Any] = {
            "local_path": local_path,
            "source_url": download_url,
            "provider_source_id": source_id,
            "width": photo.get("imageWidth", 0),
            "height": photo.get("imageHeight", 0),
            "file_size_bytes": file_bytes,
            "provider": self.provider_name,
            "license": "royalty_free",
            "is_ai_generated": False,
        }
        logger.info("pixabay_photo_downloaded", query=query, source_id=source_id)
        return ProviderResult(
            success=True, data=data,
            provider_used=self.provider_name, metadata={"query": query},
        )


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
