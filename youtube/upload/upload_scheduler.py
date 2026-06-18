"""
youtube/upload/upload_scheduler.py
"""
from __future__ import annotations
import random
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple
import structlog
from storage.supabase_client import get_db

logger = structlog.get_logger(__name__)

_DEFAULT_SHORTS_SLOTS: List[str] = ["09:00", "12:30", "15:45", "18:15", "21:00"]
_DEFAULT_LONG_SLOTS:   List[str] = ["16:00", "18:30"]
_DEFAULT_VARIANCE_MIN = 20


class UploadScheduler:

    def __init__(self) -> None:
        self._db = get_db()

    # ── Public API ────────────────────────────────────────────────────────────

    def compute_publish_time(self, video_type: str) -> datetime:
        """
        Return a timezone-aware UTC datetime for the next available publish slot
        of this video_type, applying randomized variance so publishing never
        looks perfectly mechanical.

        If today's slots are exhausted (already published or all in the past),
        rolls forward to tomorrow's first slot.
        """
        slots, variance = self._load_slots(video_type)
        now = datetime.now(timezone.utc)

        published_today = self._safe_published_today(video_type)
        start_index = min(published_today, len(slots) - 1)

        for day_offset in (0, 1):
            target_date = now.date() + timedelta(days=day_offset)
            search_from = start_index if day_offset == 0 else 0
            for i in range(search_from, len(slots)):
                slot_dt = self._slot_to_datetime(slots[i], target_date, variance)
                if slot_dt > now:
                    return slot_dt

        # Absolute fallback — should never be reached given the loop above
        return now + timedelta(hours=1)

    @staticmethod
    def to_iso(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def should_publish_now(self, scheduled_dt: datetime, lead_minutes: int = 10) -> bool:
        """
        Return True if scheduled_dt is within lead_minutes of now (or already past) —
        i.e. the caller should upload immediately as 'public' rather than scheduling
        a future publishAt.
        """
        now = datetime.now(timezone.utc)
        return scheduled_dt <= now + timedelta(minutes=lead_minutes)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_slots(self, video_type: str) -> Tuple[List[str], int]:
        rule_name = "publish_timing_shorts" if video_type == "short" else "publish_timing_long"
        defaults  = _DEFAULT_SHORTS_SLOTS if video_type == "short" else _DEFAULT_LONG_SLOTS

        try:
            rule = self._db.get_rule(rule_name)
            if isinstance(rule, dict):
                slots    = rule.get("slots_utc") or defaults
                variance = int(rule.get("variance_minutes", _DEFAULT_VARIANCE_MIN))
                if isinstance(slots, list) and slots:
                    return [str(s) for s in slots], variance
        except Exception as exc:
            logger.debug("schedule_rule_fetch_failed", rule=rule_name, error=str(exc)[:80])

        return list(defaults), _DEFAULT_VARIANCE_MIN

    def _safe_published_today(self, video_type: str) -> int:
        try:
            recent = self._db.get_recent_published(limit=30)
            today = datetime.now(timezone.utc).date()
            count = 0
            for r in recent:
                if r.get("video_type") != video_type:
                    continue
                pub_raw = r.get("published_at", "")
                if not pub_raw:
                    continue
                try:
                    pub_dt = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if pub_dt.date() == today:
                    count += 1
            return count
        except Exception as exc:
            logger.debug("published_today_lookup_failed", error=str(exc)[:80])
            return 0

    @staticmethod
    def _slot_to_datetime(slot: str, target_date: date, variance_minutes: int) -> datetime:
        hh, mm = slot.split(":")
        base = datetime(
            target_date.year, target_date.month, target_date.day,
            int(hh), int(mm), tzinfo=timezone.utc,
        )
        if variance_minutes > 0:
            jitter = random.randint(-variance_minutes, variance_minutes)
            base += timedelta(minutes=jitter)
        return base


_instance: Optional[UploadScheduler] = None

def get_upload_scheduler() -> UploadScheduler:
    global _instance
    if _instance is None:
        _instance = UploadScheduler()
    return _instance
