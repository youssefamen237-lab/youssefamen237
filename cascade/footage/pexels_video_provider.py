"""
cascade/footage/pexels_video_provider.py

Required GitHub Secret: PEXELS_API_KEY
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

_SEARCH_URL = "https://api.pexels.com/videos/search"
_QUALITY_RANK = {"full_hd": 4, "hd": 3, "sd": 2, "uhd": 5}
_MIN_FILE_BYTES = 200_000   # reject clips smaller than 200 KB


class PexelsVideoProvider(BaseProvider):
    provider_name = "pexels"
    is_free_tier = False
    cascade_category = "footage"

    def is_available(self) -> bool:
        return self.env_present("PEXELS_API_KEY")

    def execute(self, **kwargs: Any) -> ProviderResult:
        query: str = kwargs.get("query", "").strip()
        download_dir: str = kwargs.get("download_dir", "/tmp/yta_footage")
        orientation: str = kwargs.get("orientation", "landscape")
        min_dur: float = float(kwargs.get("min_duration", 3.0))
        max_dur: float = float(kwargs.get("max_duration", 45.0))

        if not query:
            return ProviderResult.failure(self.provider_name, "Empty search query.")

        api_key = os.environ["PEXELS_API_KEY"]
        headers = {"Authorization": api_key}

        try:
            resp = requests.get(
                _SEARCH_URL,
                headers=headers,
                params={
                    "query": query,
                    "per_page": 10,
                    "orientation": orientation,
                    "size": "large",
                    "min_duration": int(min_dur),
                    "max_duration": int(max_dur),
                },
                timeout=20,
            )
            if resp.status_code == 429:
                return ProviderResult.failure(
                    self.provider_name, "Pexels rate limit hit (429)."
                )
            resp.raise_for_status()
        except requests.RequestException as exc:
            return ProviderResult.failure(
                self.provider_name, f"Pexels search request failed: {exc}"
            )

        videos = resp.json().get("videos", [])
        if not videos:
            return ProviderResult.failure(
                self.provider_name, f"No Pexels videos found for: {query!r}"
            )

        # Pick the best clip
        best = self._select_best(videos, min_dur, max_dur)
        if best is None:
            return ProviderResult.failure(
                self.provider_name,
                f"No Pexels clip meets quality requirements for: {query!r}",
            )

        video_meta, file_meta = best
        download_url: str = file_meta["link"]
        source_id = str(video_meta["id"])
        filename = f"pexels_{source_id}.mp4"
        local_path = str(Path(download_dir) / filename)

        try:
            file_bytes = _stream_download(download_url, local_path)
        except Exception as exc:
            return ProviderResult.failure(
                self.provider_name, f"Pexels download failed: {exc}"
            )

        if file_bytes < _MIN_FILE_BYTES:
            Path(local_path).unlink(missing_ok=True)
            return ProviderResult.failure(
                self.provider_name,
                f"Pexels file too small ({file_bytes} bytes) — likely corrupt.",
            )

        data: Dict[str, Any] = {
            "local_path": local_path,
            "source_url": download_url,
            "provider_source_id": source_id,
            "width": file_meta.get("width", 0),
            "height": file_meta.get("height", 0),
            "duration_seconds": float(video_meta.get("duration", 0)),
            "file_size_bytes": file_bytes,
            "provider": self.provider_name,
            "license": "royalty_free",
            "is_ai_generated": False,
        }
        logger.info(
            "pexels_footage_downloaded",
            query=query,
            source_id=source_id,
            resolution=f"{data['width']}x{data['height']}",
            duration=data["duration_seconds"],
        )
        return ProviderResult(
            success=True,
            data=data,
            provider_used=self.provider_name,
            metadata={"quality": file_meta.get("quality"), "query": query},
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _select_best(
        videos: List[Dict], min_dur: float, max_dur: float
    ) -> Optional[tuple]:
        """
        Return (video_dict, video_file_dict) for the highest-quality clip
        whose duration falls within [min_dur, max_dur].
        """
        candidates = []
        for v in videos:
            dur = float(v.get("duration", 0))
            if not (min_dur <= dur <= max_dur):
                continue
            for vf in v.get("video_files", []):
                if vf.get("file_type") != "video/mp4":
                    continue
                if not vf.get("link"):
                    continue
                rank = _QUALITY_RANK.get(vf.get("quality", "sd"), 1)
                w = vf.get("width", 0)
                candidates.append((rank * 10000 + w, v, vf))

        if not candidates:
            return None
        candidates.sort(reverse=True)
        _, video_meta, file_meta = candidates[0]
        return video_meta, file_meta


def _stream_download(url: str, dest_path: str, timeout: int = 120) -> int:
    """Stream a file to dest_path. Returns bytes written."""
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
