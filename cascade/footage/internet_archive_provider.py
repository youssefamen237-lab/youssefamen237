"""
cascade/footage/internet_archive_provider.py

Searches archive.org for freely downloadable video clips.
No quota, no rate limit (be courteous with request frequency).

Required GitHub Secrets: INTERNET_ARCHIVE_ACCESS_KEY, INTERNET_ARCHIVE_SECRET_KEY
(Used for authenticated S3-style downloads; unauthenticated search is also supported.)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

_SEARCH_URL = "https://archive.org/advancedsearch.php"
_METADATA_URL = "https://archive.org/metadata/{identifier}"
_DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"
_MIN_FILE_BYTES = 500_000   # 500 KB minimum
_MAX_FILE_BYTES = 500_000_000  # 500 MB maximum (avoid huge files)
_VIDEO_FORMATS = {"h.264", "mpeg4", "cinepack", "divx", "xvid", "mp4"}


class InternetArchiveProvider(BaseProvider):
    provider_name = "internet_archive"
    is_free_tier = True     # No per-call cost
    cascade_category = "footage"

    def is_available(self) -> bool:
        # Can search without keys; secrets just enable faster downloads
        return True

    def execute(self, **kwargs: Any) -> ProviderResult:
        query: str = kwargs.get("query", "").strip()
        download_dir: str = kwargs.get("download_dir", "/tmp/yta_footage")
        min_dur: float = float(kwargs.get("min_duration", 3.0))
        max_dur: float = float(kwargs.get("max_duration", 60.0))

        if not query:
            return ProviderResult.failure(self.provider_name, "Empty search query.")

        # Step 1: Search for identifiers
        identifiers = self._search(query, rows=8)
        if not identifiers:
            return ProviderResult.failure(
                self.provider_name,
                f"No Internet Archive results for: {query!r}",
            )

        # Step 2: Find a downloadable MP4 in the first few identifiers
        for identifier in identifiers[:5]:
            result = self._try_identifier(
                identifier=identifier,
                download_dir=download_dir,
                min_dur=min_dur,
                max_dur=max_dur,
                query=query,
            )
            if result is not None:
                return result

        return ProviderResult.failure(
            self.provider_name,
            f"No downloadable MP4 found in Internet Archive results for: {query!r}",
        )

    # ── Search ────────────────────────────────────────────────────────────────

    @staticmethod
    def _search(query: str, rows: int = 8) -> List[str]:
        """Return a list of archive.org item identifiers matching the query."""
        ia_query = f"({query}) AND mediatype:movies"
        try:
            resp = requests.get(
                _SEARCH_URL,
                params={
                    "q": ia_query,
                    "output": "json",
                    "fl[]": "identifier",
                    "rows": rows,
                    "sort[]": "downloads desc",
                    "page": 1,
                },
                timeout=20,
            )
            resp.raise_for_status()
            docs = resp.json().get("response", {}).get("docs", [])
            return [d["identifier"] for d in docs if "identifier" in d]
        except Exception as exc:
            logger.warning("ia_search_error", query=query, error=str(exc))
            return []

    # ── Metadata + file selection ─────────────────────────────────────────────

    def _try_identifier(
        self,
        identifier: str,
        download_dir: str,
        min_dur: float,
        max_dur: float,
        query: str,
    ) -> Optional[ProviderResult]:
        """Try to find and download an MP4 from one archive.org item."""
        try:
            meta_resp = requests.get(
                _METADATA_URL.format(identifier=identifier),
                timeout=20,
            )
            meta_resp.raise_for_status()
            meta = meta_resp.json()
        except Exception as exc:
            logger.debug("ia_metadata_error", identifier=identifier, error=str(exc))
            return None

        files: List[Dict] = meta.get("files", [])
        candidate = self._pick_file(files)
        if candidate is None:
            return None

        filename = candidate["name"]
        file_size = int(candidate.get("size", 0))

        if file_size > _MAX_FILE_BYTES:
            logger.debug("ia_file_too_large", identifier=identifier, size=file_size)
            return None

        download_url = _DOWNLOAD_URL.format(
            identifier=identifier, filename=quote(filename)
        )
        local_filename = f"ia_{identifier[:40]}_{filename[-20:]}.mp4"
        local_filename = local_filename.replace("/", "_").replace(" ", "_")
        local_path = str(Path(download_dir) / local_filename)

        try:
            # Use IA credentials if available for authenticated download
            headers: Dict[str, str] = {}
            access = os.getenv("INTERNET_ARCHIVE_ACCESS_KEY", "").strip()
            secret = os.getenv("INTERNET_ARCHIVE_SECRET_KEY", "").strip()
            if access and secret:
                headers["Authorization"] = f"LOW {access}:{secret}"

            actual_bytes = _stream_download(download_url, local_path, headers=headers)
        except Exception as exc:
            logger.debug("ia_download_error", identifier=identifier, error=str(exc))
            return None

        if actual_bytes < _MIN_FILE_BYTES:
            Path(local_path).unlink(missing_ok=True)
            return None

        data: Dict[str, Any] = {
            "local_path": local_path,
            "source_url": download_url,
            "provider_source_id": identifier,
            "width": 1280,   # IA metadata rarely includes resolution
            "height": 720,
            "duration_seconds": float(candidate.get("length", 0)),
            "file_size_bytes": actual_bytes,
            "provider": self.provider_name,
            "license": "public_domain",
            "is_ai_generated": False,
        }
        logger.info(
            "ia_footage_downloaded",
            identifier=identifier,
            filename=filename,
            bytes=actual_bytes,
            query=query,
        )
        return ProviderResult(
            success=True,
            data=data,
            provider_used=self.provider_name,
            metadata={"identifier": identifier, "query": query},
        )

    @staticmethod
    def _pick_file(files: List[Dict]) -> Optional[Dict]:
        """
        Select the best MP4 file from an IA item's file list.
        Prefers files with format matching common MP4/H.264 descriptors,
        skipping thumbnails, subtitles, and extremely large files.
        """
        candidates = []
        for f in files:
            name: str = f.get("name", "")
            fmt: str = f.get("format", "").lower()
            size = int(f.get("size", 0))
            # Accept only .mp4 files in a reasonable size range
            if not name.lower().endswith(".mp4"):
                continue
            if size < _MIN_FILE_BYTES or size > _MAX_FILE_BYTES:
                continue
            # Skip derivative/preview files
            if any(skip in name.lower() for skip in ("_thumb", "trailer", "sample", "_512kb")):
                continue
            # Prefer h.264 / mpeg4 format descriptors
            format_rank = 2 if any(kw in fmt for kw in ("h.264", "mpeg4", "mp4")) else 1
            candidates.append((format_rank, size, f))

        if not candidates:
            return None
        # Sort by format rank DESC, then size ASC (prefer smaller for speed)
        candidates.sort(key=lambda x: (x[0], -x[1]), reverse=True)
        return candidates[0][2]


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
