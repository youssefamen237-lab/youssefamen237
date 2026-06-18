"""
cascade/footage/vecteezy_provider.py

Required GitHub Secrets: VECTEEZY_ID, VECTEEZY_SECRET_KEY
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

_API_BASE = "https://api.vecteezy.com/v1"
_MIN_FILE_BYTES = 200_000


class VecteezyProvider(BaseProvider):
    provider_name = "vecteezy"
    is_free_tier = False
    cascade_category = "footage"

    def is_available(self) -> bool:
        return self.env_present("VECTEEZY_ID", "VECTEEZY_SECRET_KEY")

    def execute(self, **kwargs: Any) -> ProviderResult:
        query: str = kwargs.get("query", "").strip()
        download_dir: str = kwargs.get("download_dir", "/tmp/yta_footage")
        min_dur: float = float(kwargs.get("min_duration", 3.0))
        max_dur: float = float(kwargs.get("max_duration", 45.0))

        if not query:
            return ProviderResult.failure(self.provider_name, "Empty search query.")

        vecteezy_id = os.environ["VECTEEZY_ID"]
        vecteezy_secret = os.environ["VECTEEZY_SECRET_KEY"]

        # Resolve auth token — try OAuth2 client_credentials first, then API key header
        token = self._get_token(vecteezy_id, vecteezy_secret)
        if token is None:
            return ProviderResult.failure(
                self.provider_name, "Could not authenticate with Vecteezy."
            )

        headers = {"Authorization": f"Bearer {token}"}

        try:
            resp = requests.get(
                f"{_API_BASE}/videos",
                headers=headers,
                params={
                    "query": query,
                    "page": 1,
                    "per_page": 10,
                    "license_type": "free",
                },
                timeout=20,
            )
            if resp.status_code in (401, 403):
                return ProviderResult.failure(
                    self.provider_name, f"Vecteezy auth rejected: HTTP {resp.status_code}."
                )
            if resp.status_code == 429:
                return ProviderResult.failure(
                    self.provider_name, "Vecteezy rate limit hit."
                )
            resp.raise_for_status()
        except requests.RequestException as exc:
            return ProviderResult.failure(
                self.provider_name, f"Vecteezy search request failed: {exc}"
            )

        try:
            payload = resp.json()
        except Exception:
            return ProviderResult.failure(
                self.provider_name, "Vecteezy response not valid JSON."
            )

        # Vecteezy may wrap results under "data", "videos", or "items"
        videos: List[Dict] = (
            payload.get("data")
            or payload.get("videos")
            or payload.get("items")
            or []
        )
        if not videos:
            return ProviderResult.failure(
                self.provider_name, f"No Vecteezy results for: {query!r}"
            )

        selection = self._select_best(videos, min_dur, max_dur)
        if selection is None:
            return ProviderResult.failure(
                self.provider_name,
                f"No Vecteezy clip meets requirements for: {query!r}",
            )

        video, download_url = selection
        source_id = str(video.get("id", "unknown"))
        filename = f"vecteezy_{source_id}.mp4"
        local_path = str(Path(download_dir) / filename)

        try:
            file_bytes = _stream_download(download_url, local_path, headers=headers)
        except Exception as exc:
            return ProviderResult.failure(
                self.provider_name, f"Vecteezy download failed: {exc}"
            )

        if file_bytes < _MIN_FILE_BYTES:
            Path(local_path).unlink(missing_ok=True)
            return ProviderResult.failure(
                self.provider_name, f"Vecteezy file too small ({file_bytes} bytes)."
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
        logger.info("vecteezy_footage_downloaded", query=query, source_id=source_id)
        return ProviderResult(
            success=True, data=data,
            provider_used=self.provider_name, metadata={"query": query},
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _get_token(client_id: str, client_secret: str) -> Optional[str]:
        """Try OAuth2 client_credentials; fall back to using secret as bearer."""
        try:
            resp = requests.post(
                f"{_API_BASE}/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json().get("access_token")
        except Exception:
            pass
        # Fallback: treat secret as a pre-issued bearer token
        return client_secret if client_secret else None

    @staticmethod
    def _select_best(
        videos: List[Dict], min_dur: float, max_dur: float
    ) -> Optional[tuple]:
        for v in videos:
            dur = float(v.get("duration", 0))
            if dur and not (min_dur <= dur <= max_dur):
                continue
            # Resolve download URL from various possible field names
            url = (
                v.get("download_url")
                or v.get("url")
                or (v.get("files", {}) or {}).get("mp4")
                or (v.get("assets", {}) or {}).get("hd")
                or (v.get("assets", {}) or {}).get("sd")
            )
            if url:
                return v, url
        return None


def _stream_download(
    url: str, dest_path: str, timeout: int = 120, headers: Optional[Dict] = None
) -> int:
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with requests.get(url, stream=True, timeout=timeout, headers=headers or {}) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as fh:
            for chunk in r.iter_content(chunk_size=32_768):
                if chunk:
                    fh.write(chunk)
                    total += len(chunk)
    return total
