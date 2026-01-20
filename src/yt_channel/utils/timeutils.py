from __future__ import annotations

from datetime import datetime, timezone, date


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_today() -> date:
    return utc_now().date()
