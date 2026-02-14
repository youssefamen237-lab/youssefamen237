"""
Automated scheduler for daily shorts and weekly long-form videos.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from yt_auto.config import Config
from yt_auto.utils import env_str


class PublishingSchedule:
    """Manages daily publishing schedule with randomized times."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.schedule_file = cfg.state_path.parent / "schedule.json"
        self.load_schedule()

    def load_schedule(self) -> None:
        """Load or create publishing schedule."""
        if self.schedule_file.exists():
            with open(self.schedule_file) as f:
                self.schedule = json.load(f)
        else:
            self.schedule = self._generate_schedule()
            self.save_schedule()

    def _generate_schedule(self) -> dict[str, Any]:
        """Generate random daily schedule."""
        # Generate seed based on current week to ensure consistency for the week
        now = datetime.now(timezone.utc)
        week_key = now.strftime("%Y-W%U")

        schedule = {
            "week": week_key,
            "shorts_slots": {},
            "long_video_day": None,
        }

        # Generate 4 random times for shorts (between 06:00-22:00 UTC)
        base_seed = abs(hash(week_key)) % (10**9)
        r = random.Random(base_seed)

        short_times = []
        for i in range(4):
            hour = r.randint(6, 21)
            minute = r.randint(0, 59)
            short_times.append(f"{hour:02d}:{minute:02d}")

        for slot, time_str in enumerate(short_times, 1):
            schedule["shorts_slots"][f"slot_{slot}"] = {
                "time": time_str,
                "published": False,
                "video_id": None,
            }

        # Choose random day for long video (between Monday-Thursday = 0-3)
        schedule["long_video_day"] = r.randint(0, 3)
        schedule["long_video_time"] = f"{r.randint(12, 18):02d}:00"

        return schedule

    def save_schedule(self) -> None:
        """Save schedule to file."""
        self.schedule_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.schedule_file, "w") as f:
            json.dump(self.schedule, f, indent=2)

    def should_publish_short(self, slot: int) -> bool:
        """Check if a short should be published now."""
        slot_key = f"slot_{slot}"
        if slot_key not in self.schedule["shorts_slots"]:
            return False

        slot_info = self.schedule["shorts_slots"][slot_key]
        if slot_info.get("published"):
            # Reset daily
            if not self._is_same_day(slot_info.get("last_published")):
                slot_info["published"] = False
                self.save_schedule()
            else:
                return False

        target_time = self._parse_time(slot_info["time"])
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)

        # Schedule has a 5-minute window
        time_match = abs((now - target_time).total_seconds()) <= 300

        return time_match

    def should_publish_long(self) -> bool:
        """Check if a long video should be published today."""
        today = datetime.now(timezone.utc)
        day_of_week = today.weekday()

        if day_of_week != self.schedule["long_video_day"]:
            return False

        target_time = self._parse_time(self.schedule["long_video_time"])
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)

        time_match = abs((now - target_time).total_seconds()) <= 300

        return time_match

    def mark_short_published(self, slot: int, video_id: str) -> None:
        """Mark a short as published."""
        slot_key = f"slot_{slot}"
        if slot_key in self.schedule["shorts_slots"]:
            self.schedule["shorts_slots"][slot_key]["published"] = True
            self.schedule["shorts_slots"][slot_key]["video_id"] = video_id
            self.schedule["shorts_slots"][slot_key]["last_published"] = datetime.now(
                timezone.utc
            ).isoformat()
            self.save_schedule()

    def mark_long_published(self, video_id: str) -> None:
        """Mark long video as published."""
        self.schedule["long_video_published"] = True
        self.schedule["long_video_id"] = video_id
        self.schedule["long_published_date"] = datetime.now(timezone.utc).isoformat()
        self.save_schedule()

    def _parse_time(self, time_str: str) -> datetime:
        """Parse HH:MM time string to today's datetime."""
        now = datetime.now(timezone.utc)
        try:
            hour, minute = map(int, time_str.split(":"))
            return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except (ValueError, AttributeError):
            return now

    def _is_same_day(self, iso_str: str | None) -> bool:
        """Check if ISO datetime string is from today."""
        if not iso_str:
            return False
        try:
            dt = datetime.fromisoformat(iso_str)
            today = datetime.now(timezone.utc).date()
            return dt.date() == today
        except (ValueError, AttributeError):
            return False

    def get_daily_stats(self) -> dict[str, Any]:
        """Get daily publishing statistics."""
        return {
            "week": self.schedule["week"],
            "shorts_published_today": sum(
                1
                for slot in self.schedule["shorts_slots"].values()
                if slot.get("published") and self._is_same_day(slot.get("last_published"))
            ),
            "long_scheduled_today": self.should_publish_long(),
            "schedule": self.schedule,
        }


class RateLimiter:
    """Rate limiter for API calls and publishing."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.rate_file = cfg.state_path.parent / "rate_limits.json"
        self.load_limits()

    def load_limits(self) -> None:
        """Load rate limit history."""
        if self.rate_file.exists():
            with open(self.rate_file) as f:
                self.limits = json.load(f)
        else:
            self.limits = {}

    def save_limits(self) -> None:
        """Save rate limit history."""
        self.rate_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.rate_file, "w") as f:
            json.dump(self.limits, f, indent=2)

    def check_publish_limit(self, content_type: str) -> bool:
        """Check if publish limit is exceeded."""
        now = datetime.now(timezone.utc)
        hour_key = now.strftime("%Y-%m-%d-%H")

        if content_type == "short":
            max_per_hour = self.cfg.RATE_LIMIT_SHORTS_PER_HOUR
            counter_key = f"shorts_{hour_key}"
        elif content_type == "long":
            max_per_hour = self.cfg.RATE_LIMIT_LONG_PER_HOUR
            counter_key = f"long_{hour_key}"
        else:
            return True

        count = self.limits.get(counter_key, 0)
        return count < max_per_hour

    def record_publish(self, content_type: str) -> None:
        """Record a publish event."""
        now = datetime.now(timezone.utc)
        hour_key = now.strftime("%Y-%m-%d-%H")

        if content_type == "short":
            counter_key = f"shorts_{hour_key}"
        elif content_type == "long":
            counter_key = f"long_{hour_key}"
        else:
            return

        self.limits[counter_key] = self.limits.get(counter_key, 0) + 1
        self.save_limits()

    def cleanup_old_limits(self, keep_days: int = 7) -> None:
        """Clean up old rate limit records."""
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=keep_days)).date()

        keys_to_remove = []
        for key in self.limits:
            try:
                date_str = "-".join(key.split("-")[:3])
                key_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if key_date < cutoff:
                    keys_to_remove.append(key)
            except (ValueError, IndexError):
                continue

        for key in keys_to_remove:
            del self.limits[key]

        self.save_limits()
