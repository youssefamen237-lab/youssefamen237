from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def in_hours(dt: datetime, hours: int) -> datetime:
    return dt + timedelta(hours=hours)


def today_utc_ymd() -> str:
    return utc_now().strftime("%Y-%m-%d")
