"""
core/visuals.py
===============
Fetches human-interaction stock video clips from Pexels (primary)
and Pixabay (fallback).  Downloads the best matching clip to disk
and returns its local path for use by video_editor.py.
"""

import random
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

from config.api_keys import get_pexels_key, get_pixabay_key
from config.settings import (
    OUTPUT_CLIPS_DIR,
    PEXELS_API_BASE,
    PEXELS_MIN_CLIP_DURATION,
    PEXELS_RESULTS_PER_PAGE,
    PIXABAY_API_BASE,
    PIXABAY_RESULTS_PER_PAGE,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
    VISUAL_SEARCH_QUERIES,
)
from utils.fallback import run_with_fallback
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger(__name__)

# Extra queries focused exclusively on human interaction
_HUMAN_QUERIES: list[str] = [
    "people talking conversation",
    "friends laughing together",
    "person thinking seriously",
    "couple discussing emotion",
    "team collaboration office",
    "student studying psychology",
    "therapist listening patient",
    "crowd social behavior",
    "person walking city",
    "human eye contact close up",
]

# Minimum acceptable clip duration in seconds
_MIN_DURATION: int = PEXELS_MIN_CLIP_DURATION

# Preferred video quality label order (highest first)
_PEXELS_QUALITY_PREFS: list[str] = ["hd", "sd", "hls"]


@dataclass
class ClipResult:
    """
    Describes a downloaded stock video clip.

    Attributes
    ----------
    local_path   : Absolute path to the downloaded .mp4 file.
    duration     : Clip duration in seconds (from API metadata).
    source       : 'pexels' | 'pixabay'
    query        : Search query that found this clip.
    clip_id      : Provider's own video ID (for dedup / attribution).
    """
    local_path:  Path
    duration:    int
    source:      str
    query:       str
    clip_id:     str


class VisualsEngine:
    """
    Downloads a relevant human-interaction clip for a given psychology topic.

    Strategy
    --------
    1. Build a topic-aware search query (topic keyword + human interaction term).
    2. Try Pexels → if no results, try Pixabay.
    3. From the results, pick a random qualifying clip (duration ≥ threshold)
       to avoid always using the first result (anti-bot humanization).
    4. Download the clip to OUTPUT_CLIPS_DIR and return a ClipResult.

    Parameters
    ----------
    output_dir : Directory for downloaded clips.  Created if missing.
    """

    def __init__(self, output_dir: Path = OUTPUT_CLIPS_DIR) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._pexels_key  = get_pexels_key()
        self._pixabay_key = get_pixabay_key()

    # ── Public ─────────────────────────────────────────────────────────────

    def fetch_clip(self, topic: str, required_duration: float) -> ClipResult:
        """
        Fetch and download one clip relevant to `topic`.

        Parameters
        ----------
        topic             : Psychology topic keyword from the script.
        required_duration : Minimum clip length in seconds (= video duration).
                            Clips shorter than this are rejected.

        Returns
        -------
        ClipResult with the downloaded file path.

        Raises
        ------
        RuntimeError : Both Pexels and Pixabay returned no usable clips.
        """
        query = self._build_query(topic)
        min_dur = max(int(required_duration) + 1, _MIN_DURATION)

        logger.info("Visuals: fetching clip — query='%s' min_dur=%ds", query, min_dur)

        result = run_with_fallback(
            primary=lambda: self._fetch_pexels(query, min_dur),
            fallback=lambda: self._fetch_pixabay(query, min_dur),
            primary_name="Pexels",
            fallback_name="Pixabay",
        )
        return result

    # ── Query builder ───────────────────────────────────────────────────────

    @staticmethod
    def _build_query(topic: str) -> str:
        """
        Combine the psychology topic with a random human-interaction modifier
        to keep footage grounded in human behaviour (not abstract imagery).
        """
        base  = topic.split()[0] if topic else "psychology"
        human = random.choice(_HUMAN_QUERIES)
        # Weight: 50% use topic + modifier, 50% use a pure human query
        if random.random() < 0.5:
            return f"{base} {human}"
        return human

    # ── Pexels ──────────────────────────────────────────────────────────────

    @with_retry()
    def _fetch_pexels(self, query: str, min_dur: int) -> ClipResult:
        params = {
            "query":        query,
            "per_page":     PEXELS_RESULTS_PER_PAGE,
            "orientation":  "portrait",          # 9:16 preferred
            "size":         "medium",
        }
        resp = requests.get(
            PEXELS_API_BASE,
            headers={"Authorization": self._pexels_key},
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        videos = data.get("videos", [])
        if not videos:
            raise RuntimeError(f"Pexels returned 0 results for query='{query}'")

        # Filter by duration
        qualified = [v for v in videos if v.get("duration", 0) >= min_dur]
        if not qualified:
            # Relax the filter — take any clip and let editor loop it
            qualified = videos
            logger.warning(
                "Pexels: no clip ≥ %ds for query='%s' — using shortest available.",
                min_dur, query,
            )

        # Random pick from top-5 to avoid deterministic first-result bias
        video = random.choice(qualified[:5])
        video_files = video.get("video_files", [])

        # Pick best quality file
        download_url = self._best_pexels_file(video_files)
        clip_id      = str(video.get("id", uuid.uuid4()))
        duration     = int(video.get("duration", min_dur))

        local_path = self._download(download_url, clip_id, "pexels")

        return ClipResult(
            local_path=local_path,
            duration=duration,
            source="pexels",
            query=query,
            clip_id=clip_id,
        )

    @staticmethod
    def _best_pexels_file(video_files: list[dict]) -> str:
        """Return the URL of the highest-quality file available."""
        for quality in _PEXELS_QUALITY_PREFS:
            for f in video_files:
                if f.get("quality") == quality and f.get("link"):
                    return f["link"]
        # Fallback: first file with any link
        for f in video_files:
            if f.get("link"):
                return f["link"]
        raise RuntimeError("No downloadable file found in Pexels video_files.")

    # ── Pixabay ─────────────────────────────────────────────────────────────

    @with_retry()
    def _fetch_pixabay(self, query: str, min_dur: int) -> ClipResult:
        params = {
            "key":          self._pixabay_key,
            "q":            query,
            "video_type":   "film",
            "per_page":     PIXABAY_RESULTS_PER_PAGE,
            "safesearch":   "true",
            "order":        "popular",
        }
        resp = requests.get(
            PIXABAY_API_BASE,
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        hits = data.get("hits", [])
        if not hits:
            raise RuntimeError(f"Pixabay returned 0 results for query='{query}'")

        qualified = [h for h in hits if h.get("duration", 0) >= min_dur]
        if not qualified:
            qualified = hits
            logger.warning(
                "Pixabay: no clip ≥ %ds for query='%s' — using shortest available.",
                min_dur, query,
            )

        video    = random.choice(qualified[:5])
        clip_id  = str(video.get("id", uuid.uuid4()))
        duration = int(video.get("duration", min_dur))

        # Pixabay provides multiple sizes; prefer 'large' then 'medium'
        videos_dict = video.get("videos", {})
        download_url = (
            videos_dict.get("large",  {}).get("url")
            or videos_dict.get("medium", {}).get("url")
            or videos_dict.get("small",  {}).get("url")
        )
        if not download_url:
            raise RuntimeError(f"Pixabay video {clip_id} has no downloadable URL.")

        local_path = self._download(download_url, clip_id, "pixabay")

        return ClipResult(
            local_path=local_path,
            duration=duration,
            source="pixabay",
            query=query,
            clip_id=clip_id,
        )

    # ── Downloader ──────────────────────────────────────────────────────────

    @with_retry()
    def _download(self, url: str, clip_id: str, source: str) -> Path:
        """Stream-download a video file to disk. Returns the local path."""
        out_path = self._output_dir / f"{source}_{clip_id}.mp4"

        if out_path.exists() and out_path.stat().st_size > 10_000:
            logger.debug("Clip already cached: %s", out_path)
            return out_path

        logger.info("Downloading clip: %s → %s", url[:80], out_path.name)
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    f.write(chunk)

        if out_path.stat().st_size < 10_000:
            out_path.unlink(missing_ok=True)
            raise RuntimeError(f"Downloaded clip is suspiciously small: {url}")

        logger.info("Clip saved: %s (%.1f MB)", out_path.name,
                    out_path.stat().st_size / 1_048_576)
        return out_path
