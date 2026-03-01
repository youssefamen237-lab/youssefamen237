"""
utils/rate_limiter.py – Quizzaro Rate Limiter
==============================================
Token-bucket rate limiter per API name.
Prevents hitting free-tier limits for Gemini, Groq, Freesound, Pexels, etc.
All limits are conservative (well under actual free-tier caps).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

from loguru import logger


@dataclass
class Bucket:
    calls_per_minute: int
    _timestamps: list[float] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)


# Conservative per-minute call limits for each free-tier API
API_LIMITS: dict[str, int] = {
    "gemini": 10,
    "groq": 20,
    "openrouter": 10,
    "freesound": 15,
    "pexels": 20,
    "pixabay": 20,
    "newsapi": 10,
    "youtube_data": 5,
    "youtube_analytics": 5,
    "wikipedia": 30,
    "pytrends": 5,
}


class RateLimiter:

    def __init__(self) -> None:
        self._buckets: dict[str, Bucket] = {
            name: Bucket(calls_per_minute=limit)
            for name, limit in API_LIMITS.items()
        }

    def wait(self, api: str) -> None:
        """
        Block until a call to *api* is within the rate limit.
        Creates a permissive bucket if the API is unknown.
        """
        if api not in self._buckets:
            self._buckets[api] = Bucket(calls_per_minute=30)

        bucket = self._buckets[api]
        with bucket._lock:
            now = time.monotonic()
            window = 60.0
            # Remove timestamps older than 1 minute
            bucket._timestamps = [t for t in bucket._timestamps if now - t < window]

            if len(bucket._timestamps) >= bucket.calls_per_minute:
                oldest = bucket._timestamps[0]
                sleep_for = window - (now - oldest) + 0.1
                if sleep_for > 0:
                    logger.debug(f"[RateLimiter] '{api}' limit reached. Sleeping {sleep_for:.1f}s …")
                    time.sleep(sleep_for)
                # Re-clean after sleep
                now = time.monotonic()
                bucket._timestamps = [t for t in bucket._timestamps if now - t < window]

            bucket._timestamps.append(time.monotonic())
