"""
cascade/footage/footage_cascade.py

Footage Cascade Coordinator — single import point for all video clip retrieval.

Provider order (Pexels → Pixabay → Coverr → Internet Archive → Vecteezy)
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Dict, Optional

import structlog

from cascade.base_provider import ProviderResult
from cascade.cascade_manager import CascadeManager, CircuitBreaker
from cascade.footage.coverr_provider import CoverrProvider
from cascade.footage.internet_archive_provider import InternetArchiveProvider
from cascade.footage.pexels_video_provider import PexelsVideoProvider
from cascade.footage.pixabay_video_provider import PixabayVideoProvider
from cascade.footage.vecteezy_provider import VecteezyProvider

logger = structlog.get_logger(__name__)

_SHARED_BREAKER = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=300)


@dataclass
class FootageResult:
    """Normalised result returned by FootageCascade.search_and_download()."""
    local_path: str
    source_url: str
    provider_source_id: str
    width: int
    height: int
    duration_seconds: float
    file_size_bytes: int
    provider: str
    license: str = "royalty_free"
    is_ai_generated: bool = False


class FootageCascade:
    """
    Singleton facade for all footage retrieval.
    Used exclusively by the media_fetcher engine.
    """

    def __init__(self) -> None:
        self._pexels = PexelsVideoProvider()
        self._pixabay = PixabayVideoProvider()
        self._coverr = CoverrProvider()
        self._ia = InternetArchiveProvider()
        self._vecteezy = VecteezyProvider()

    # ═════════════════════════════════════════════════════════════════════════
    # Public API
    # ═════════════════════════════════════════════════════════════════════════

    def search_and_download(
        self,
        query: str,
        download_dir: Optional[str] = None,
        orientation: str = "landscape",
        min_duration: float = 3.0,
        max_duration: float = 45.0,
    ) -> FootageResult:
        """
        Search all providers for a clip matching `query` and download it locally.

        Parameters
        ──────────
        query        Search term (e.g. "orca hunting shark ocean")
        download_dir Local directory for downloaded files.  Defaults to a temp dir.
        orientation  "landscape" or "portrait"
        min_duration Minimum clip length in seconds
        max_duration Maximum clip length in seconds

        Returns FootageResult on success.
        Raises RuntimeError if every provider fails.
        """
        if not query.strip():
            raise ValueError("search_and_download() received empty query.")

        if download_dir is None:
            download_dir = tempfile.mkdtemp(prefix="yta_footage_")

        os.makedirs(download_dir, exist_ok=True)

        manager = CascadeManager(
            providers=self._ordered_providers(),
            category="footage",
            max_retries_per_provider=1,   # footage search is expensive — 1 retry only
            circuit_breaker=_SHARED_BREAKER,
        )

        result: ProviderResult = manager.execute(
            query=query,
            download_dir=download_dir,
            orientation=orientation,
            min_duration=min_duration,
            max_duration=max_duration,
        )

        if not result.success:
            raise RuntimeError(
                f"Footage cascade exhausted for query={query!r}. "
                f"Error: {result.error}"
            )

        d = result.data
        footage = FootageResult(
            local_path=d["local_path"],
            source_url=d["source_url"],
            provider_source_id=d["provider_source_id"],
            width=d["width"],
            height=d["height"],
            duration_seconds=d["duration_seconds"],
            file_size_bytes=d["file_size_bytes"],
            provider=result.provider_used,
            license=d.get("license", "royalty_free"),
            is_ai_generated=d.get("is_ai_generated", False),
        )
        logger.info(
            "footage_cascade_success",
            query=query,
            provider=footage.provider,
            duration=footage.duration_seconds,
            resolution=f"{footage.width}x{footage.height}",
        )
        return footage

    # ═════════════════════════════════════════════════════════════════════════
    # Multiple queries (batch)
    # ═════════════════════════════════════════════════════════════════════════

    def search_multiple(
        self,
        queries: list,
        download_dir: Optional[str] = None,
        orientation: str = "landscape",
        min_duration: float = 3.0,
        max_duration: float = 30.0,
    ) -> list:
        """
        Search for multiple clips (one per query) and return a list of FootageResults.
        Skips failed queries rather than raising — the caller handles missing clips.
        """
        if download_dir is None:
            download_dir = tempfile.mkdtemp(prefix="yta_footage_batch_")

        results = []
        for query in queries:
            try:
                footage = self.search_and_download(
                    query=query,
                    download_dir=download_dir,
                    orientation=orientation,
                    min_duration=min_duration,
                    max_duration=max_duration,
                )
                results.append(footage)
            except RuntimeError as exc:
                logger.warning(
                    "footage_batch_query_failed",
                    query=query,
                    error=str(exc),
                )
                results.append(None)   # None signals "no clip found for this segment"
        return results

    # ═════════════════════════════════════════════════════════════════════════
    # Diagnostics
    # ═════════════════════════════════════════════════════════════════════════

    def get_status(self) -> Dict:
        return {
            "category": "footage",
            "providers": [
                p.provider_name for p in self._ordered_providers()
            ],
            "circuit_status": _SHARED_BREAKER.get_status(),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _ordered_providers(self) -> list:
        """Return providers in fixed priority order."""
        return [
            self._pexels,
            self._pixabay,
            self._coverr,
            self._ia,
            self._vecteezy,
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Singleton accessor
# ─────────────────────────────────────────────────────────────────────────────

_footage_instance: Optional[FootageCascade] = None


def get_footage() -> FootageCascade:
    global _footage_instance
    if _footage_instance is None:
        _footage_instance = FootageCascade()
    return _footage_instance
