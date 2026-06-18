"""
engines/media_fetcher.py
"""
from __future__ import annotations
import os, tempfile
from typing import List, Optional
import structlog
from engines.video_assembler import MediaItem
from cascade.footage.footage_cascade import get_footage
from cascade.images.image_cascade import get_images
from cascade.ai_images.ai_images_cascade import get_ai_images

logger = structlog.get_logger(__name__)


class MediaFetcher:

    def __init__(self) -> None:
        self._footage    = get_footage()
        self._images     = get_images()
        self._ai_images  = get_ai_images()

    def fetch_all_segments(
        self,
        segments:     List[dict],
        download_dir: str,
        video_type:   str = "short",
    ) -> List[Optional[MediaItem]]:
        """
        For each segment dict (keys: sentence, search_query) fetch one media item.
        Order: real footage → still image → AI-generated image → None (black frame).
        """
        os.makedirs(download_dir, exist_ok=True)
        orientation = "portrait" if video_type == "short" else "landscape"
        results: List[Optional[MediaItem]] = []

        for i, seg in enumerate(segments):
            query    = (seg.get("search_query") or seg.get("sentence", "nature")).strip()
            sentence = seg.get("sentence", query)
            item     = self._fetch_one(query, sentence, i, download_dir, orientation)
            results.append(item)
            logger.debug(
                "segment_media_result",
                index=i,
                query=query[:50],
                found=item is not None,
                provider=item.provider if item else "none",
            )

        found = sum(1 for r in results if r is not None)
        logger.info("media_fetched_all", total=len(segments), found=found,
                    ai_count=sum(1 for r in results if r and r.provider.startswith(("ai_","getimg","stability","dezgo","horde"))))
        return results

    def _fetch_one(
        self,
        query:       str,
        sentence:    str,
        index:       int,
        download_dir:str,
        orientation: str,
    ) -> Optional[MediaItem]:

        # ── 1. Real footage (video clip) ──────────────────────────────────────
        try:
            f = self._footage.search_and_download(
                query=query,
                download_dir=download_dir,
                orientation=orientation,
                min_duration=3.0,
                max_duration=30.0,
            )
            return MediaItem(
                local_path=f.local_path, asset_type="video",
                provider=f.provider, width=f.width, height=f.height,
                segment_index=index, search_query=query,
                duration_seconds=f.duration_seconds,
            )
        except Exception as exc:
            logger.debug("footage_miss", query=query[:40], error=str(exc)[:80])

        # ── 2. Still image ────────────────────────────────────────────────────
        try:
            img = self._images.search_and_download(
                query=query,
                download_dir=download_dir,
                orientation=orientation,
            )
            return MediaItem(
                local_path=img.local_path, asset_type="image",
                provider=img.provider, width=img.width, height=img.height,
                segment_index=index, search_query=query,
                duration_seconds=None,
            )
        except Exception as exc:
            logger.debug("image_miss", query=query[:40], error=str(exc)[:80])

        # ── 3. AI-generated image ─────────────────────────────────────────────
        try:
            ai_prompt = (
                f"{sentence} ultra-realistic wildlife nature photography "
                "high detail professional"
            )
            ai = self._ai_images.generate_image(
                prompt=ai_prompt, download_dir=download_dir,
            )
            return MediaItem(
                local_path=ai.local_path, asset_type="image",
                provider=ai.provider, width=ai.width, height=ai.height,
                segment_index=index, search_query=query,
                duration_seconds=None,
            )
        except Exception as exc:
            logger.warning("all_media_failed", query=query[:40], error=str(exc)[:100])

        return None


_instance: Optional[MediaFetcher] = None

def get_media_fetcher() -> MediaFetcher:
    global _instance
    if _instance is None:
        _instance = MediaFetcher()
    return _instance
