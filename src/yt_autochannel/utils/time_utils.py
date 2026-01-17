from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Tuple

import pytz


def now_utc() -> datetime:
    return datetime.now(tz=pytz.UTC)


def to_utc(dt_local: datetime) -> datetime:
    if dt_local.tzinfo is None:
        raise ValueError("dt_local must be timezone-aware")
    return dt_local.astimezone(pytz.UTC)


def parse_hhmm(hhmm: str) -> Tuple[int, int]:
    parts = hhmm.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid HH:MM: {hhmm}")
    return int(parts[0]), int(parts[1])


def jitter_seconds(base: int, jitter: int) -> int:
    if jitter <= 0:
        return base
    return max(0, base + random.randint(-jitter, jitter))


def daily_time_slots_utc(
    timezone_name: str,
    date_local: datetime,
    hhmm_list: List[str],
    jitter_s: int,
) -> List[datetime]:
    tz = pytz.timezone(timezone_name)
    if date_local.tzinfo is None:
        date_local = tz.localize(date_local)
    date_local = date_local.astimezone(tz)
    slots: List[datetime] = []
    for hhmm in hhmm_list:
        h, m = parse_hhmm(hhmm)
        candidate = tz.localize(datetime(date_local.year, date_local.month, date_local.day, h, m, 0))
        candidate = candidate + timedelta(seconds=random.randint(-jitter_s, jitter_s))
        slots.append(candidate.astimezone(pytz.UTC))
    slots.sort()
    return slots
