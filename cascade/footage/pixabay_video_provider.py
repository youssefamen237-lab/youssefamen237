"""
cascade/footage/pixabay_video_provider.py

Required GitHub Secret: PIXABAY_API_KEY
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

_SEARCH_URL = "https://pixabay.com/api/videos/"
_MIN_FILE_BYTES = 200_000
# Quality tiers in descending preference
_TIERS: List[str] = ["large", "medium", "small"]


class PixabayVideoProvider(BaseProvider):
    provider_name = "pixabay"
    is_free_tier = False
    cascade_category = "footage"

    def is_available(self) -> bool:
        return self.env_present("PIXABAY_API_KEY")

    def execute(self, **kwargs: Any) -> ProviderResult:
        query: str = kwargs.get("query", "").strip()
        download_dir: str = kwargs.get("download_dir", "/tmp/yta_footage")
        min_dur: float = float(kwargs.get("min_duration", 3.0))
        max_dur: float = float(kwargs.get("max_duration", 45.0))

        if not query:
            return ProviderResult.failure(self.provider_name, "Empty search query.")

        api_key = os.environ["PIXABAY_API_KEY"]

        try:
            resp = requests.get(
                _SEARCH_URL,
                params={
                    "key": api_key,
                    "q": query,
                    "per_page": 10,
                    "video_type": "film",
                    "min_width": 1280,
                    "safesearch": "true",
                },
                timeout=20,
            )
            if resp.status_code == 429:
                return ProviderResult.failure(
                    self.provider_name, "Pixabay rate limit hit (429)."
                )
            resp.raise_for_status()
        except requests.RequestException as exc:
            return ProviderResult.failure(
                self.provider_name, f"Pixabay search request failed: {exc}"
            )

        hits: List[Dict] = resp.json().get("hits", [])
        if not hits:
            return ProviderResult.failure(
                self.provider_name, f"No Pixabay videos found for: {query!r}"
            )

        selection = self._select_best(hits, min_dur, max_dur)
        if selection is None:
            return ProviderResult.failure(
                self.provider_name,
                f"No Pixabay clip meets duration requirements for: {query!r}",
            )

        hit, tier_key, tier_data = selection
        download_url: str = tier_data["url"]
        source_id = str(hit["id"])
        filename = f"pixabay_{source_id}.mp4"
        local_path = str(Path(download_dir) / filename)

        try:
            file_bytes = _stream_download(download_url, local_path)
        except Exception as exc:
            return ProviderResult.failure(
                self.provider_name, f"Pixabay download failed: {exc}"
            )

        if file_bytes < _MIN_FILE_BYTES:
            Path(local_path).unlink(missing_ok=True)
            return ProviderResult.failure(
                self.provider_name,
                f"Pixabay file too small ({file_bytes} bytes).",
            )

        w = tier_data.get("width", 0)
        h = tier_data.get("height", 0)
        data: Dict[str, Any] = {
            "local_path": local_path,
            "source_url": download_url,
            "provider_source_id": source_id,
            "width": w,
            "height": h,
            "duration_seconds": float(hit.get("duration", 0)),
            "file_size_bytes": file_bytes,
            "provider": self.provider_name,
            "license": "royalty_free",
            "is_ai_generated": False,
        }
        logger.info(
            "pixabay_footage_downloaded",
            query=query,
            source_id=source_id,
            tier=tier_key,
            resolution=f"{w}x{h}",
        )
        return ProviderResult(
            success=True,
            data=data,
            provider_used=self.provider_name,
            metadata={"tier": tier_key, "query": query},
        )

    @staticmethod
    def _select_best(
        hits: List[Dict], min_dur: float, max_dur: float
    ) -> Optional[Tuple[Dict, str, Dict]]:
        """
        Return (hit, tier_name, tier_dict) for the best available clip
        within the duration window.
        """
        for hit in hits:
            dur = float(hit.get("duration", 0))
            if not (min_dur <= dur <= max_dur):
                continue
            vids: Dict = hit.get("videos", {})
            for tier in _TIERS:
                tier_data = vids.get(tier)
                if tier_data and tier_data.get("url"):
                    return hit, tier, tier_data
        return None


def _stream_download(url: str, dest_path: str, timeout: int = 120) -> int:
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as fh:
            for chunk in r.iter_content(chunk_size=32_768):
                if chunk:
                    fh.write(chunk)
                    total += len(chunk)
    return total
