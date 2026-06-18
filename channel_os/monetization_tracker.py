"""
channel_os/monetization_tracker.py

Tracks progress toward standard YouTube Partner Program monetization
(1,000 subscribers + 4,000 public watch hours in the trailing 365 days),
using the isolated management credential set (Key 4).

Writes a `channel_dna` learning_memory entry ("monetization_status") that
reporting/daily_dashboard.py and channel_os/cos.py can read.

Run via: python -m channel_os.monetization_tracker
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
import structlog

from storage.supabase_client import get_db
from youtube.management.management_client import get_management_client

logger = structlog.get_logger(__name__)

_SUBSCRIBER_THRESHOLD   = 1000
_WATCH_HOURS_THRESHOLD  = 4000
_TRAILING_DAYS          = 365
_DATA_LAG_DAYS          = 2

_CHANNEL_METRICS = ["estimatedMinutesWatched", "views", "subscribersGained"]


class MonetizationTracker:

    def __init__(self) -> None:
        self._db     = get_db()
        self._client = get_management_client()

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self) -> Dict:
        stats = self._safe(lambda: self._client.get_channel_statistics(), {})
        subscriber_count = int(stats.get("subscriber_count", 0))

        end_date   = (datetime.now(timezone.utc) - timedelta(days=_DATA_LAG_DAYS)).date()
        start_date = end_date - timedelta(days=_TRAILING_DAYS)

        analytics = self._safe(
            lambda: self._client.query_channel_analytics(
                start_date.isoformat(), end_date.isoformat(), _CHANNEL_METRICS,
            ),
            {},
        )

        watch_minutes = float(analytics.get("estimatedMinutesWatched", 0))
        watch_hours   = round(watch_minutes / 60.0, 2)
        views_trailing       = int(analytics.get("views", 0))
        subs_gained_trailing = int(analytics.get("subscribersGained", 0))

        subs_remaining  = max(0, _SUBSCRIBER_THRESHOLD - subscriber_count)
        hours_remaining = max(0.0, round(_WATCH_HOURS_THRESHOLD - watch_hours, 2))

        eligible = (
            subscriber_count >= _SUBSCRIBER_THRESHOLD
            and watch_hours >= _WATCH_HOURS_THRESHOLD
        )

        status = {
            "checked_at":                       datetime.now(timezone.utc).isoformat(),
            "subscriber_count":                 subscriber_count,
            "subscriber_threshold":             _SUBSCRIBER_THRESHOLD,
            "subscribers_remaining":            subs_remaining,
            "watch_hours_trailing_365d":        watch_hours,
            "watch_hours_threshold":            _WATCH_HOURS_THRESHOLD,
            "watch_hours_remaining":            hours_remaining,
            "views_trailing_365d":              views_trailing,
            "subscribers_gained_trailing_365d": subs_gained_trailing,
            "standard_monetization_eligible":   eligible,
        }

        try:
            self._db.upsert_memory(
                memory_type="channel_dna", memory_key="monetization_status",
                memory_value=status, confidence=100.0, data_points=1,
            )
        except Exception as exc:
            logger.warning("monetization_status_write_failed", error=str(exc)[:120])

        logger.info(
            "monetization_status_updated",
            subscribers=subscriber_count, watch_hours=watch_hours, eligible=eligible,
        )
        return status

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _safe(fn, default):
        try:
            return fn()
        except Exception as exc:
            logger.warning("monetization_tracker_step_failed", error=str(exc)[:120])
            return default


_instance: Optional[MonetizationTracker] = None

def get_monetization_tracker() -> MonetizationTracker:
    global _instance
    if _instance is None:
        _instance = MonetizationTracker()
    return _instance


if __name__ == "__main__":
    import json
    result = get_monetization_tracker().run()
    print(json.dumps(result, indent=2, default=str))
