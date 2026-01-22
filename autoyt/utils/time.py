\
from __future__ import annotations

import datetime as _dt
from typing import Iterable, List, Optional, Tuple

import pytz


def utc_now() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.timezone.utc)


def to_timezone(dt: _dt.datetime, tz_name: str) -> _dt.datetime:
    tz = pytz.timezone(tz_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(tz)


def isoformat_rfc3339(dt: _dt.datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def jitter_minutes(rng, minutes_min: int, minutes_max: int) -> int:
    return int(rng.randint(minutes_min, minutes_max))


def spaced_times_for_day(
    day_local: _dt.date,
    tz_name: str,
    hours_local: List[int],
    jitter_min: int,
    jitter_max: int,
    min_gap_minutes: int,
    seed: int,
) -> List[_dt.datetime]:
    """
    Create publish datetimes (UTC) from local hour targets + jitter with spacing constraints.
    Deterministic using seed.
    """
    rng = __import__("random").Random(seed)
    tz = pytz.timezone(tz_name)

    candidates: List[_dt.datetime] = []
    for h in hours_local:
        base_local = tz.localize(_dt.datetime.combine(day_local, _dt.time(h, 0, 0)))
        j = jitter_minutes(rng, jitter_min, jitter_max)
        dt_local = base_local + _dt.timedelta(minutes=j)
        candidates.append(dt_local)

    # sort and enforce min gap
    candidates.sort()
    spaced: List[_dt.datetime] = []
    for dt_local in candidates:
        if not spaced:
            spaced.append(dt_local)
            continue
        gap = (dt_local - spaced[-1]).total_seconds() / 60.0
        if gap < min_gap_minutes:
            dt_local = spaced[-1] + _dt.timedelta(minutes=min_gap_minutes)
        spaced.append(dt_local)

    # convert to UTC
    return [dt.astimezone(_dt.timezone.utc) for dt in spaced]


def pick_seed_for_date(day: _dt.date) -> int:
    return int(day.strftime("%Y%m%d"))
