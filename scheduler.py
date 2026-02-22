"""
Smart Scheduler — decides WHEN to publish based on audience analytics.
Analyzes best times for US/UK/CA foreign audiences.
No fixed cron times — purely data-driven dynamic scheduling.

Best times for English-speaking foreign audiences (research-based defaults):
- US East:  7AM, 12PM, 5PM, 9PM (EST = UTC-5)
- US West:  7AM, 12PM, 5PM, 9PM (PST = UTC-8)
- UK:       8AM, 1PM, 6PM, 9PM  (GMT = UTC+0 or UTC+1)
- CA:       follows US East times

Optimal UTC posting windows that cover all these markets:
  Slot 1: 12:00 UTC  = 7AM EST / 4AM PST / 12PM GMT  (US morning + UK noon)
  Slot 2: 17:00 UTC  = 12PM EST / 9AM PST / 5PM GMT   (US lunch + UK evening)
  Slot 3: 22:00 UTC  = 5PM EST / 2PM PST / 10PM GMT   (US after-work peak)
  Slot 4: 02:00 UTC  = 9PM EST / 6PM PST / 2AM GMT    (US prime night)
"""

import os
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

STRATEGY_FILE = Path("data/analytics/current_strategy.json")
SCHEDULE_LOG  = Path("data/published/schedule_log.json")
SCHEDULE_LOG.parent.mkdir(parents=True, exist_ok=True)

# Default posting slots (UTC hours) — best for US/UK/CA combined
DEFAULT_SLOTS_UTC = [12, 17, 22, 2]

# Slots specifically good per audience
AUDIENCE_SLOTS = {
    "US_East":  [12, 17, 22, 2],   # 7AM, 12PM, 5PM, 9PM EST
    "US_West":  [15, 20, 1, 5],    # 7AM, 12PM, 5PM, 9PM PST
    "UK":       [8, 13, 18, 21],   # 8AM, 1PM, 6PM, 9PM GMT
    "CA_East":  [12, 17, 22, 2],   # Same as US East
}

# Tolerance window (±30 min) — vary slightly to avoid robot patterns
SLOT_JITTER_MINUTES = 25


def load_strategy():
    if STRATEGY_FILE.exists():
        with open(STRATEGY_FILE) as f:
            return json.load(f)
    return {}


def load_schedule_log():
    if SCHEDULE_LOG.exists():
        with open(SCHEDULE_LOG) as f:
            return json.load(f)
    return []


def save_schedule_log(log):
    with open(SCHEDULE_LOG, "w") as f:
        json.dump(log, f, indent=2)


def get_optimal_slots_utc() -> list:
    """
    Return optimal UTC posting hours based on analytics strategy.
    Falls back to research-based defaults if no analytics data yet.
    """
    strategy = load_strategy()
    analytics_hours = strategy.get("best_posting_hours", [])

    if analytics_hours and len(analytics_hours) >= 2:
        # Use analytics-derived hours if we have enough data
        print(f"[Scheduler] Using analytics-derived posting hours: {analytics_hours}")
        return sorted(analytics_hours)

    # No analytics yet — use proven research-based defaults
    # These cover US morning + lunch + after-work + night AND UK daytime/evening
    print(f"[Scheduler] Using research-based default slots: {DEFAULT_SLOTS_UTC}")
    return DEFAULT_SLOTS_UTC


def get_today_published(video_type: str = None) -> list:
    """Get videos published today"""
    log = load_schedule_log()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries = [e for e in log if e.get("date", "").startswith(today)]
    if video_type:
        entries = [e for e in entries if e.get("type") == video_type]
    return entries


def get_week_published_long() -> list:
    """Get long videos published this week"""
    log = load_schedule_log()
    week_start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    return [e for e in log if e.get("type") == "long" and e.get("date", "") >= week_start]


def should_publish_short_now() -> tuple:
    """
    Determine if it's a good time to publish a Short right now.
    Returns (should_publish: bool, reason: str)
    """
    now_utc = datetime.now(timezone.utc)
    current_hour = now_utc.hour
    current_minute = now_utc.minute

    # Check daily limit
    today_shorts = get_today_published("short")
    if len(today_shorts) >= 4:
        return False, f"Daily limit reached ({len(today_shorts)}/4 shorts today)"

    # Check minimum gap between shorts (2 hours)
    if today_shorts:
        last_pub = today_shorts[-1].get("date", "")
        if last_pub:
            try:
                last_dt = datetime.fromisoformat(last_pub.replace("Z", "+00:00"))
                elapsed_hours = (now_utc - last_dt).total_seconds() / 3600
                if elapsed_hours < 2.0:
                    return False, f"Too soon since last short ({elapsed_hours:.1f}h < 2h min)"
            except Exception:
                pass

    # Check if current time is near an optimal slot
    optimal_slots = get_optimal_slots_utc()
    for slot_hour in optimal_slots:
        # Check if we're within ±SLOT_JITTER_MINUTES of a slot
        slot_start = slot_hour * 60 - SLOT_JITTER_MINUTES
        slot_end   = slot_hour * 60 + SLOT_JITTER_MINUTES
        current_min_total = current_hour * 60 + current_minute

        # Handle midnight wraparound
        if slot_hour == 0 or slot_hour == 1 or slot_hour == 2:
            if current_hour >= 23:
                current_min_total = (current_hour - 24) * 60 + current_minute

        if slot_start <= current_min_total <= slot_end:
            # This slot hasn't been used today yet?
            slot_already_used = any(
                abs(_hour_of(e.get("date", "")) - slot_hour) <= 1
                for e in today_shorts
            )
            if not slot_already_used:
                return True, f"Optimal slot {slot_hour:02d}:00 UTC (window active)"

    return False, f"Not in an optimal posting window (current UTC hour: {current_hour})"


def should_publish_long_now() -> tuple:
    """
    Determine if it's a good time to publish a Long video now.
    """
    now_utc = datetime.now(timezone.utc)
    current_weekday = now_utc.weekday()  # 0=Mon, 6=Sun

    # Long videos: Mon, Wed, Fri, Sun
    long_days = [0, 2, 4, 6]
    if current_weekday not in long_days:
        return False, f"Not a long-video day (today={now_utc.strftime('%A')})"

    # Check weekly limit
    week_longs = get_week_published_long()
    if len(week_longs) >= 4:
        return False, f"Weekly limit reached ({len(week_longs)}/4 long videos)"

    # Check if already published a long today
    today_longs = get_today_published("long")
    if today_longs:
        return False, "Already published long video today"

    # Best time for long videos: 9AM-1PM EST = 14:00-18:00 UTC
    good_long_hours = [14, 15, 16, 17, 18]
    if now_utc.hour not in good_long_hours:
        return False, f"Not in long-video time window (ideal: 14-18 UTC, now: {now_utc.hour})"

    return True, f"Good time for long video ({now_utc.strftime('%A')} {now_utc.hour:02d}:00 UTC)"


def _hour_of(iso_str: str) -> int:
    """Extract UTC hour from ISO datetime string"""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.hour
    except Exception:
        return -1


def log_scheduled_publish(video_type: str, video_id: str, title: str):
    """Record a successful publish for scheduling decisions"""
    log = load_schedule_log()
    log.append({
        "type": video_type,
        "video_id": video_id,
        "title": title[:80],
        "date": datetime.now(timezone.utc).isoformat(),
    })
    if len(log) > 1000:
        log = log[-1000:]
    save_schedule_log(log)


def get_schedule_summary() -> dict:
    """Return current scheduling state"""
    today_shorts = get_today_published("short")
    today_longs  = get_today_published("long")
    week_longs   = get_week_published_long()
    slots        = get_optimal_slots_utc()
    now_utc      = datetime.now(timezone.utc)

    should_short, short_reason = should_publish_short_now()
    should_long, long_reason   = should_publish_long_now()

    return {
        "current_utc": now_utc.strftime("%Y-%m-%d %H:%M UTC"),
        "current_day": now_utc.strftime("%A"),
        "optimal_slots_utc": slots,
        "shorts_today": len(today_shorts),
        "longs_today": len(today_longs),
        "longs_this_week": len(week_longs),
        "should_publish_short": should_short,
        "short_reason": short_reason,
        "should_publish_long": should_long,
        "long_reason": long_reason,
    }


if __name__ == "__main__":
    summary = get_schedule_summary()
    print(json.dumps(summary, indent=2))
