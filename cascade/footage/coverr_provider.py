"""
cascade/footage/coverr_provider.py

Required GitHub Secrets: COVERR_API_ID, COVERR_API_KEY
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

_SEARCH_URL = "https://api.coverr.co/videos"
_MIN_FILE_BYTES = 200_000


class CoverrProvider(BaseProvider):
    provider_name = "coverr"
    is_free_tier = False
    cascade_category = "footage"

    def is_available(self) -> bool:
        return self.env_present("COVERR_API_ID", "COVERR_API_KEY")

    def execute(self, **kwargs: Any) -> ProviderResult:
        query: str = kwargs.get("query", "").strip()
        download_dir: str = kwargs.get("download_dir", "/tmp/yta_footage")
        min_dur: float = float(kwargs.get("min_duration", 3.0))
        max_dur: float = float(kwargs.get("max_duration", 45.0))

        if not query:
            return ProviderResult.failure(self.provider_name, "Empty search query.")

        api_id = os.environ["COVERR_API_ID"]
        api_key = os.environ["COVERR_API_KEY"]

        # Coverr API: Bearer token formed from api_id:api_key or plain api_key
        # Try both auth formats — plain key first, then combined
        auth_header = f"Bearer {api_key}"

        try:
            resp = requests.get(
                _SEARCH_URL,
                headers={"Authorization": auth_header},
                params={"q": query, "page": 1, "limit": 10},
                timeout=20,
            )
            if resp.status_code in (401, 403):
                # Try alternative: api_id as token
                resp = requests.get(
                    _SEARCH_URL,
                    headers={"Authorization": f"Bearer {api_id}"},
                    params={"q": query, "page": 1, "limit": 10},
                    timeout=20,
                )
            if resp.status_code == 429:
                return ProviderResult.failure(
                    self.provider_name, "Coverr rate limit hit (429)."
                )
            resp.raise_for_status()
        except requests.RequestException as exc:
            return ProviderResult.failure(
                self.provider_name, f"Coverr search request failed: {exc}"
            )

        try:
            payload = resp.json()
        except Exception as exc:
            return ProviderResult.failure(
                self.provider_name, f"Coverr response not valid JSON: {exc}"
            )

        # Coverr returns {"hits": [...]} or {"videos": [...]}
        videos: List[Dict] = payload.get("hits") or payload.get("videos") or []
        if not videos:
            return ProviderResult.failure(
                self.provider_name, f"No Coverr videos for: {query!r}"
            )

        selection = self._select_best(videos, min_dur, max_dur)
        if selection is None:
            return ProviderResult.failure(
                self.provider_name,
                f"No Coverr clip meets requirements for: {query!r}",
            )

        video, download_url = selection
        source_id = str(video.get("id", "unknown"))
        filename = f"coverr_{source_id}.mp4"
        local_path = str(Path(download_dir) / filename)

        try:
            file_bytes = _stream_download(download_url, local_path)
        except Exception as exc:
            return ProviderResult.failure(
                self.provider_name, f"Coverr download failed: {exc}"
            )

        if file_bytes < _MIN_FILE_BYTES:
            Path(local_path).unlink(missing_ok=True)
            return ProviderResult.failure(
                self.provider_name, f"Coverr file too small ({file_bytes} bytes)."
            )

        data: Dict[str, Any] = {
            "local_path": local_path,
            "source_url": download_url,
            "provider_source_id": source_id,
            "width": video.get("width", 1280),
            "height": video.get("height", 720),
            "duration_seconds": float(video.get("duration", 0)),
            "file_size_bytes": file_bytes,
            "provider": self.provider_name,
            "license": "royalty_free",
            "is_ai_generated": False,
        }
        logger.info(
            "coverr_footage_downloaded",
            query=query,
            source_id=source_id,
        )
        return ProviderResult(
            success=True,
            data=data,
            provider_used=self.provider_name,
            metadata={"query": query},
        )

    @staticmethod
    def _select_best(
        videos: List[Dict], min_dur: float, max_dur: float
    ) -> Optional[tuple]:
        """Return (video_dict, download_url) for the best eligible clip."""
        for v in videos:
            dur = float(v.get("duration", 0))
            if dur and not (min_dur <= dur <= max_dur):
                continue
            # Coverr nests URLs under "urls" or directly under "url"
            urls: Dict = v.get("urls", {})
            url = (
                urls.get("url_hd")
                or urls.get("url_hd720")
                or urls.get("url_sd")
                or v.get("url")
                or v.get("download_url")
                or v.get("mp4")
            )
            if url:
                return v, url
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
