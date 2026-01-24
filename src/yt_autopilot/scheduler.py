\
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .state import iso_utc, parse_iso_utc, utc_now

logger = logging.getLogger(__name__)


def _get_top_hours(config: Dict[str, Any]) -> List[int]:
    learned = (((config.get("analysis") or {}).get("learned") or {}).get("top_hours_utc")) if isinstance((config.get("analysis") or {}).get("learned"), dict) else None
    if isinstance(learned, list) and learned:
        return [int(h) % 24 for h in learned if isinstance(h, (int, float, str))]
    # fallback
    return [14, 17, 20, 23, 2, 5, 8, 11]


def _jitter_minutes() -> int:
    return random.randint(-18, 18)


def _make_datetime_for_hour(day: datetime, hour: int) -> datetime:
    base = day.replace(hour=hour, minute=0, second=0, microsecond=0)
    base += timedelta(minutes=_jitter_minutes())
    return base


def _is_same_week(a: datetime, b: datetime) -> bool:
    wa = a.isocalendar()
    wb = b.isocalendar()
    return (wa.year, wa.week) == (wb.year, wb.week)


def refresh_schedule(state: Any, config: Dict[str, Any]) -> None:
    pub_cfg = config.get("publishing") or {}
    content_cfg = config.get("content") or {}

    shorts_per_day = int(content_cfg.get("shorts_per_day", 4))
    longs_per_week = int(content_cfg.get("longs_per_week", 4))
    hard_short_cap = int(pub_cfg.get("max_shorts_per_day_hard_cap", max(4, shorts_per_day)))
    hard_long_cap = int(pub_cfg.get("max_longs_per_week_hard_cap", max(4, longs_per_week)))

    now = utc_now()
    last = state.last_schedule_refresh_utc
    if last:
        try:
            last_dt = parse_iso_utc(last)
            if (now - last_dt) < timedelta(hours=10):
                return
        except Exception:
            pass

    # remove old items
    new_schedule: List[Dict[str, Any]] = []
    for it in state.schedule:
        try:
            due = parse_iso_utc(it["due_utc"])
            if due < now - timedelta(hours=6):
                continue
            if it.get("status") == "posted":
                continue
            new_schedule.append(it)
        except Exception:
            continue
    state.schedule = new_schedule

    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # ensure we have shorts for next 24h
    due_times: List[datetime] = []
    top_hours = _get_top_hours(config)
    candidates = top_hours[:]
    random.shuffle(candidates)

    for h in candidates:
        if len(due_times) >= shorts_per_day:
            break
        dt = _make_datetime_for_hour(today, int(h))
        if dt < now + timedelta(minutes=10):
            dt += timedelta(days=1)
        due_times.append(dt)

    # fill remaining randomly
    while len(due_times) < shorts_per_day:
        h = random.randint(0, 23)
        dt = _make_datetime_for_hour(today, h)
        if dt < now + timedelta(minutes=10):
            dt += timedelta(days=1)
        due_times.append(dt)

    due_times = sorted(due_times)[:shorts_per_day]

    # daily counter
    day_key = now.date().isoformat()
    today_count = int(((state.daily_counters.get(day_key) or {}).get("shorts_scheduled") or 0))
    can_schedule_more = max(0, min(hard_short_cap, shorts_per_day) - today_count)

    for dt in due_times[:can_schedule_more]:
        state.schedule.append(
            {
                "id": f"{iso_utc(dt)}_short",
                "kind": "short",
                "due_utc": iso_utc(dt),
                "status": "pending",
                "video_id": None,
            }
        )
        state.daily_counters.setdefault(day_key, {})
        state.daily_counters[day_key]["shorts_scheduled"] = int(state.daily_counters[day_key].get("shorts_scheduled", 0)) + 1

    # weekly long scheduling (spread across the week)
    wk_key = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    wk_count = int(((state.weekly_counters.get(wk_key) or {}).get("longs_scheduled") or 0))
    remaining_week = max(0, min(hard_long_cap, longs_per_week) - wk_count)
    if remaining_week > 0:
        # schedule long on random day among next 6 days if not already scheduled
        existing_long_dates = set()
        for it in state.schedule:
            if it.get("kind") == "long":
                try:
                    existing_long_dates.add(parse_iso_utc(it["due_utc"]).date().isoformat())
                except Exception:
                    pass

        days_ahead = list(range(0, 7))
        random.shuffle(days_ahead)
        for da in days_ahead:
            if remaining_week <= 0:
                break
            dt_day = today + timedelta(days=da)
            if dt_day.date().isoformat() in existing_long_dates:
                continue
            hour = random.choice(top_hours[:4] if len(top_hours) >= 4 else top_hours)
            dt = _make_datetime_for_hour(dt_day, int(hour))
            if dt < now + timedelta(minutes=30):
                continue
            state.schedule.append(
                {
                    "id": f"{iso_utc(dt)}_long",
                    "kind": "long",
                    "due_utc": iso_utc(dt),
                    "status": "pending",
                    "video_id": None,
                }
            )
            state.weekly_counters.setdefault(wk_key, {})
            state.weekly_counters[wk_key]["longs_scheduled"] = int(state.weekly_counters[wk_key].get("longs_scheduled", 0)) + 1
            remaining_week -= 1

    state.last_schedule_refresh_utc = iso_utc(now)
