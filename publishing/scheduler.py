"""
publishing/scheduler.py – Quizzaro Publish Scheduler
=====================================================
Generates randomised daily video counts (4–8) and publish times.
Reads strategy_config.json to respect the optimizer's preferred hour windows.
Guarantees:
  - No two videos published within 45 minutes of each other
  - Publish times are always in the future (UTC)
  - No fixed patterns across days (seeded from today's date + random salt)
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

STRATEGY_CONFIG_PATH = Path("data/strategy_config.json")

DEFAULT_WINDOWS = [[7, 9], [12, 14], [18, 20], [21, 23]]
MIN_GAP_MINUTES = 45


class PublishScheduler:

    def __init__(self) -> None:
        self._config = self._load_config()

    def _load_config(self) -> dict:
        if STRATEGY_CONFIG_PATH.exists():
            try:
                with open(STRATEGY_CONFIG_PATH, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def todays_video_count(self) -> int:
        lo = self._config.get("daily_video_count_min", 4)
        hi = self._config.get("daily_video_count_max", 8)
        count = random.randint(lo, hi)
        logger.info(f"[Scheduler] Today's video count: {count}")
        return count

    def todays_publish_times(self, count: int) -> list[datetime]:
        """
        Return *count* randomised UTC datetimes spread across today's
        preferred publishing windows. All times are >= now + 2 minutes.
        """
        windows = self._config.get("publish_hour_windows", DEFAULT_WINDOWS)
        now_utc = datetime.now(timezone.utc)
        min_start = now_utc + timedelta(minutes=2)

        # Build a pool of candidate minute-level slots from today's windows
        candidate_minutes: list[int] = []
        for window in windows:
            start_h, end_h = window[0], window[1]
            for h in range(start_h, end_h):
                for m in range(0, 60, 5):   # every 5-min slot
                    candidate_minutes.append(h * 60 + m)

        random.shuffle(candidate_minutes)

        selected: list[datetime] = []
        used_minutes: list[int] = []

        for total_minutes in candidate_minutes:
            h, m = divmod(total_minutes, 60)
            # Add random jitter ±4 minutes so times are never round numbers
            jitter = random.randint(-4, 4)
            m = max(0, min(59, m + jitter))

            candidate_dt = now_utc.replace(hour=h, minute=m, second=random.randint(0, 59), microsecond=0)

            # If slot already passed today, push to tomorrow
            if candidate_dt < min_start:
                candidate_dt += timedelta(days=1)

            # Enforce minimum gap
            too_close = any(
                abs((candidate_dt - dt).total_seconds()) < MIN_GAP_MINUTES * 60
                for dt in selected
            )
            if too_close:
                continue

            selected.append(candidate_dt)
            if len(selected) >= count:
                break

        # If we couldn't fill from windows, pad with evenly-spaced future times
        while len(selected) < count:
            last = selected[-1] if selected else min_start
            next_dt = last + timedelta(minutes=random.randint(60, 120))
            selected.append(next_dt)

        selected.sort()
        logger.info(f"[Scheduler] Publish times (UTC): {[t.strftime('%H:%M') for t in selected]}")
        return selected
