"""
cascade/images/freepik_provider.py

Required GitHub Secret: FREEPIK_API_KEY
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

_API_BASE = "https://api.freepik.com/v1"
_MIN_FILE_BYTES = 50_000


class FreepikProvider(BaseProvider):
    provider_name = "freepik"
    is_free_tier = False
    cascade_category = "images"

    def is_available(self) -> bool:
        return self.env_present("FREEPIK_API_KEY")

    def execute(self, **kwargs: Any) -> ProviderResult:
        query: str = kwargs.get("query", "").strip()
        download_dir: str = kwargs.get("download_dir", "/tmp/yta_images")
        min_width: int = int(kwargs.get("min_width", 1280))

        if not query:
            return ProviderResult.failure(self.provider_name, "Empty search query.")

        api_key = os.environ["FREEPIK_API_KEY"]
        headers = {
            "X-Freepik-API-Key": api_key,
            "Accept-Language": "en-US",
        }

        try:
            resp = requests.get(
                f"{_API_BASE}/resources",
                headers=headers,
                params={
                    "term": query,
                    "filters[content_type][photo]": 1,
                    "filters[license][freemium]": 1,
                    "page": 1,
                    "limit": 10,
                    "order": "relevance",
                    "locale": "en-US",
                },
                timeout=20,
            )
            if resp.status_code in (401, 403):
                return ProviderResult.failure(
                    self.provider_name,
                    f"Freepik API auth failed: HTTP {resp.status_code}.",
                )
            if resp.status_code == 429:
                return ProviderResult.failure(self.provider_name, "Freepik rate limit.")
            resp.raise_for_status()
        except requests.RequestException as exc:
            return ProviderResult.failure(
                self.provider_name, f"Freepik search failed: {exc}"
            )

        try:
            data_items: List[Dict] = resp.json().get("data", [])
        except Exception:
            return ProviderResult.failure(self.provider_name, "Freepik response not valid JSON.")

        if not data_items:
            return ProviderResult.failure(
                self.provider_name, f"No Freepik results for: {query!r}"
            )

        # Find the first item with a downloadable URL
        for item in data_items:
            source_id = str(item.get("id", "unknown"))
            # Freepik embeds download URL under links.download or thumbnail
            links: Dict = item.get("links", {})
            download_url = links.get("download") or links.get("www")
            thumbnail: Dict = item.get("thumbnail", {})
            img_url = (
                download_url
                or thumbnail.get("url")
                or item.get("url")
            )
            if not img_url:
                continue

            filename = f"freepik_{source_id}.jpg"
            local_path = str(Path(download_dir) / filename)

            try:
                file_bytes = _download_image(img_url, local_path, headers=headers)
            except Exception as exc:
                logger.debug(
                    "freepik_download_attempt_failed",
                    source_id=source_id,
                    error=str(exc),
                )
                continue

            if file_bytes < _MIN_FILE_BYTES:
                Path(local_path).unlink(missing_ok=True)
                continue

            result_data: Dict[str, Any] = {
                "local_path": local_path,
                "source_url": img_url,
                "provider_source_id": source_id,
                "width": item.get("width", min_width),
                "height": item.get("height", 720),
                "file_size_bytes": file_bytes,
                "provider": self.provider_name,
                "license": "freemium",
                "is_ai_generated": False,
            }
            logger.info("freepik_image_downloaded", query=query, source_id=source_id)
            return ProviderResult(
                success=True,
                data=result_data,
                provider_used=self.provider_name,
                metadata={"query": query},
            )

        return ProviderResult.failure(
            self.provider_name,
            f"No downloadable Freepik images found for: {query!r}",
        )


def _download_image(
    url: str, dest_path: str, timeout: int = 60, headers: Optional[Dict] = None
) -> int:
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with requests.get(url, stream=True, timeout=timeout, headers=headers or {}) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as fh:
            for chunk in r.iter_content(chunk_size=16_384):
                if chunk:
                    fh.write(chunk)
                    total += len(chunk)
    return total
