"""
cascade/images/unsplash_provider.py

Required GitHub Secrets: UNSPLASH_ACCESS_KEY
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

_SEARCH_URL = "https://api.unsplash.com/search/photos"
_MIN_FILE_BYTES = 50_000   # 50 KB minimum for a usable image


class UnsplashProvider(BaseProvider):
    provider_name = "unsplash"
    is_free_tier = False
    cascade_category = "images"

    def is_available(self) -> bool:
        return self.env_present("UNSPLASH_ACCESS_KEY")

    def execute(self, **kwargs: Any) -> ProviderResult:
        query: str = kwargs.get("query", "").strip()
        download_dir: str = kwargs.get("download_dir", "/tmp/yta_images")
        orientation: str = kwargs.get("orientation", "landscape")
        min_width: int = int(kwargs.get("min_width", 1280))

        if not query:
            return ProviderResult.failure(self.provider_name, "Empty search query.")

        access_key = os.environ["UNSPLASH_ACCESS_KEY"]
        headers = {
            "Authorization": f"Client-ID {access_key}",
            "Accept-Version": "v1",
        }

        # Map orientation to Unsplash values
        unsplash_orient = {"portrait": "portrait", "landscape": "landscape"}.get(
            orientation.lower(), "landscape"
        )

        try:
            resp = requests.get(
                _SEARCH_URL,
                headers=headers,
                params={
                    "query": query,
                    "per_page": 10,
                    "orientation": unsplash_orient,
                    "content_filter": "high",
                },
                timeout=20,
            )
            if resp.status_code == 429:
                return ProviderResult.failure(
                    self.provider_name, "Unsplash rate limit hit (429)."
                )
            resp.raise_for_status()
        except requests.RequestException as exc:
            return ProviderResult.failure(
                self.provider_name, f"Unsplash search failed: {exc}"
            )

        results = resp.json().get("results", [])
        if not results:
            return ProviderResult.failure(
                self.provider_name, f"No Unsplash images for: {query!r}"
            )

        photo = self._select_best(results, min_width)
        if photo is None:
            return ProviderResult.failure(
                self.provider_name,
                f"No Unsplash image meets width requirement ({min_width}px).",
            )

        # Prefer "full" URL; fall back to "regular"
        urls: Dict = photo.get("urls", {})
        download_url = urls.get("full") or urls.get("regular") or urls.get("raw")
        if not download_url:
            return ProviderResult.failure(
                self.provider_name, "Unsplash returned photo with no URL."
            )

        source_id = photo.get("id", "unknown")
        filename = f"unsplash_{source_id}.jpg"
        local_path = str(Path(download_dir) / filename)

        try:
            file_bytes = _download_image(download_url, local_path)
        except Exception as exc:
            return ProviderResult.failure(
                self.provider_name, f"Unsplash download failed: {exc}"
            )

        if file_bytes < _MIN_FILE_BYTES:
            Path(local_path).unlink(missing_ok=True)
            return ProviderResult.failure(
                self.provider_name, f"Unsplash image too small ({file_bytes} bytes)."
            )

        # Trigger download event (Unsplash API requires this for tracking)
        dl_link = photo.get("links", {}).get("download_location")
        if dl_link:
            try:
                requests.get(
                    dl_link, headers=headers, timeout=10
                )
            except Exception:
                pass

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
            "author": photo.get("user", {}).get("name", ""),
        }
        logger.info(
            "unsplash_image_downloaded",
            query=query,
            source_id=source_id,
            resolution=f"{data['width']}x{data['height']}",
        )
        return ProviderResult(
            success=True, data=data,
            provider_used=self.provider_name, metadata={"query": query},
        )

    @staticmethod
    def _select_best(photos: List[Dict], min_width: int) -> Optional[Dict]:
        candidates = [
            p for p in photos
            if p.get("width", 0) >= min_width and p.get("urls", {}).get("regular")
        ]
        if not candidates:
            # Relax width constraint
            candidates = [p for p in photos if p.get("urls", {}).get("regular")]
        if not candidates:
            return None
        # Pick highest resolution
        return max(candidates, key=lambda p: p.get("width", 0) * p.get("height", 0))


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
