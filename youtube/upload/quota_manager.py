"""
youtube/upload/quota_manager.py
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import structlog
from storage.redis_client import get_redis

logger = structlog.get_logger(__name__)

UNITS_PER_UPLOAD = 1_600
DAILY_LIMIT      = 9_000   # buffer below YouTube's 10,000-unit hard cap
UPLOAD_KEYS      = (1, 2, 3)


@dataclass
class QuotaStatus:
    key_index: int
    used:      int
    remaining: int


class QuotaManager:

    def __init__(self) -> None:
        self._redis = get_redis()

    def get_best_key(self) -> Optional[int]:
        """Return the upload key index (1-3) with the most remaining quota, or None if all exhausted."""
        return self._redis.get_best_yt_upload_key(
            units_per_upload=UNITS_PER_UPLOAD, daily_limit=DAILY_LIMIT
        )

    def record_upload(self, key_index: int, units: int = UNITS_PER_UPLOAD) -> int:
        return self._redis.add_yt_upload_units(key_index, units)

    def get_status(self) -> List[QuotaStatus]:
        out: List[QuotaStatus] = []
        for k in UPLOAD_KEYS:
            used = self._redis.get_yt_upload_units_used(k)
            out.append(QuotaStatus(k, used, max(0, DAILY_LIMIT - used)))
        return out

    def total_remaining_uploads(self) -> int:
        return sum(s.remaining // UNITS_PER_UPLOAD for s in self.get_status())

    def any_capacity_available(self) -> bool:
        return self.get_best_key() is not None


_instance: Optional[QuotaManager] = None

def get_quota_manager() -> QuotaManager:
    global _instance
    if _instance is None:
        _instance = QuotaManager()
    return _instance
