"""
cascade/images/image_cascade.py
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Dict, Optional

import structlog

from cascade.base_provider import ProviderResult
from cascade.cascade_manager import CascadeManager, CircuitBreaker
from cascade.images.freepik_provider import FreepikProvider
from cascade.images.pexels_photo_provider import PexelsPhotoProvider
from cascade.images.pixabay_photo_provider import PixabayPhotoProvider
from cascade.images.unsplash_provider import UnsplashProvider

logger = structlog.get_logger(__name__)
_SHARED_BREAKER = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=300)


@dataclass
class ImageResult:
    local_path: str
    source_url: str
    provider_source_id: str
    width: int
    height: int
    file_size_bytes: int
    provider: str
    license: str = "royalty_free"
    is_ai_generated: bool = False


class ImageCascade:
    def __init__(self) -> None:
        self._unsplash = UnsplashProvider()
        self._pexels = PexelsPhotoProvider()
        self._pixabay = PixabayPhotoProvider()
        self._freepik = FreepikProvider()

    def search_and_download(
        self,
        query: str,
        download_dir: Optional[str] = None,
        orientation: str = "landscape",
        min_width: int = 1280,
    ) -> ImageResult:
        if not query.strip():
            raise ValueError("search_and_download() received empty query.")
        if download_dir is None:
            download_dir = tempfile.mkdtemp(prefix="yta_images_")
        os.makedirs(download_dir, exist_ok=True)

        manager = CascadeManager(
            providers=[self._unsplash, self._pexels, self._pixabay, self._freepik],
            category="images",
            max_retries_per_provider=1,
            circuit_breaker=_SHARED_BREAKER,
        )
        result: ProviderResult = manager.execute(
            query=query,
            download_dir=download_dir,
            orientation=orientation,
            min_width=min_width,
        )
        if not result.success:
            raise RuntimeError(
                f"Image cascade exhausted for query={query!r}. Error: {result.error}"
            )
        d = result.data
        image = ImageResult(
            local_path=d["local_path"],
            source_url=d["source_url"],
            provider_source_id=d["provider_source_id"],
            width=d["width"],
            height=d["height"],
            file_size_bytes=d["file_size_bytes"],
            provider=result.provider_used,
            license=d.get("license", "royalty_free"),
            is_ai_generated=d.get("is_ai_generated", False),
        )
        logger.info(
            "image_cascade_success",
            query=query,
            provider=image.provider,
            resolution=f"{image.width}x{image.height}",
        )
        return image

    def get_status(self) -> Dict:
        return {
            "category": "images",
            "circuit_status": _SHARED_BREAKER.get_status(),
        }


_images_instance: Optional[ImageCascade] = None


def get_images() -> ImageCascade:
    global _images_instance
    if _images_instance is None:
        _images_instance = ImageCascade()
    return _images_instance
