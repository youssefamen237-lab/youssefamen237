from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Sequence, Tuple

import random

from .text import choose_weighted


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_tz(dt: datetime, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def parse_window(window: str) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    window = window.strip()
    a, b = window.split("-", 1)
    ah, am = a.split(":")
    bh, bm = b.split(":")
    return (int(ah), int(am)), (int(bh), int(bm))


def _hour_weight(perf_publish_hours: Dict[str, dict], hour: int) -> float:
    rec = perf_publish_hours.get(str(hour))
    if not isinstance(rec, dict):
        return 1.0
    count = max(1, int(rec.get("count", 0)))
    avg = float(rec.get("views24_sum", 0.0)) / float(count)
    return 1.0 + min(50.0, max(0.0, avg / 50.0))


def plan_times_for_day(
    *,
    now_utc: datetime,
    tz_name: str,
    candidate_windows: Sequence[str],
    count: int,
    min_lead_minutes: int,
    perf_publish_hours: Dict[str, dict],
) -> List[datetime]:
    tz = ZoneInfo(tz_name)
    now_local = now_utc.astimezone(tz)
    today = now_local.date()

    planned: List[datetime] = []
    windows = list(candidate_windows)
    if not windows:
        windows = ["09:00-22:00"]

    # If count <= len(windows): pick distinct windows; else allow reuse.
    window_order: List[str] = []
    if count <= len(windows):
        window_order = random.sample(windows, k=count)
    else:
        window_order = [random.choice(windows) for _ in range(count)]

    lead_cutoff_local = now_local + timedelta(minutes=min_lead_minutes)

    for win in window_order:
        (sh, sm), (eh, em) = parse_window(win)

        start = datetime(today.year, today.month, today.day, sh, sm, tzinfo=tz)
        end = datetime(today.year, today.month, today.day, eh, em, tzinfo=tz)
        if end <= start:
            end = end + timedelta(days=1)

        # Enforce lead cutoff
        if end <= lead_cutoff_local:
            start = lead_cutoff_local
            end = lead_cutoff_local + timedelta(hours=2)

        if start < lead_cutoff_local:
            start = lead_cutoff_local

        # Build candidate hours within [start,end)
        start_hour = start.hour
        end_hour = end.hour
        hours: List[int] = []
        # If crosses midnight, handle simply by iterating minutes from start to end in 30-min steps.
        if start.date() != end.date():
            # fallback: pick random between start and end
            delta_seconds = int((end - start).total_seconds())
            if delta_seconds < 60:
                dt = start
            else:
                dt = start + timedelta(seconds=random.randint(0, delta_seconds - 1))
            planned.append(dt)
            continue

        for h in range(start_hour, end_hour + 1):
            hours.append(h)

        if not hours:
            hours = [start.hour]

        weights = [_hour_weight(perf_publish_hours, h) for h in hours]
        chosen_hour = choose_weighted(hours, weights)

        # Choose minute bounds for chosen hour within window
        if chosen_hour == start.hour:
            minute_min = start.minute
        else:
            minute_min = 0
        if chosen_hour == end.hour:
            minute_max = max(0, end.minute - 1)
        else:
            minute_max = 59
        if minute_max < minute_min:
            minute_min, minute_max = 0, 59

        chosen_minute = random.randint(minute_min, minute_max)
        dt = datetime(today.year, today.month, today.day, chosen_hour, chosen_minute, tzinfo=tz)

        # Ensure lead cutoff
        if dt < lead_cutoff_local:
            dt = lead_cutoff_local

        planned.append(dt)

    planned.sort()
    # Deduplicate and ensure monotonic spacing (>= 20 minutes)
    out: List[datetime] = []
    for dt in planned:
        if not out:
            out.append(dt)
            continue
        prev = out[-1]
        if dt <= prev:
            dt = prev + timedelta(minutes=25)
        elif (dt - prev) < timedelta(minutes=20):
            dt = prev + timedelta(minutes=20)
        out.append(dt)

    return out
