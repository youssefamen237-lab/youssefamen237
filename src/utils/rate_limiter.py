"""
Rate Limiter & Safety Layer — enforces posting limits, avoids spam patterns,
protects channel from strikes, ensures compliance with YouTube policies.
"""

import os
import json
import time
import random
from datetime import datetime, timedelta
from pathlib import Path

SAFETY_LOG = Path("data/published/safety_log.json")
SAFETY_LOG.parent.mkdir(parents=True, exist_ok=True)

# Limits per day to stay safe
DAILY_SHORTS_LIMIT = 4
DAILY_LONG_LIMIT = 1  # Per day (4 per week)
MIN_HOURS_BETWEEN_SHORTS = 2
MIN_HOURS_BETWEEN_ANY_UPLOAD = 1

# Content safety
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 5000
MAX_TAGS = 500
FORBIDDEN_WORDS_IN_METADATA = []  # YouTube ToS violations — kept as runtime check


def load_safety_log():
    if SAFETY_LOG.exists():
        with open(SAFETY_LOG) as f:
            return json.load(f)
    return []


def save_safety_log(log):
    with open(SAFETY_LOG, "w") as f:
        json.dump(log, f, indent=2)


def get_today_uploads():
    log = load_safety_log()
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    return [e for e in log if e.get("date", "").startswith(today_str)]


def get_this_week_long_uploads():
    log = load_safety_log()
    week_start = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    return [e for e in log if e.get("type") == "long" and e.get("date", "") >= week_start]


def can_upload_short():
    """Check if we can safely upload another Short today"""
    today = get_today_uploads()
    shorts_today = [e for e in today if e.get("type") == "short"]

    if len(shorts_today) >= DAILY_SHORTS_LIMIT:
        print(f"[Safety] Daily short limit reached ({DAILY_SHORTS_LIMIT})")
        return False, f"Daily short limit {DAILY_SHORTS_LIMIT} reached"

    if shorts_today:
        last_short_time = shorts_today[-1].get("date", "")
        if last_short_time:
            try:
                last_dt = datetime.fromisoformat(last_short_time)
                elapsed = (datetime.utcnow() - last_dt).total_seconds() / 3600
                if elapsed < MIN_HOURS_BETWEEN_SHORTS:
                    wait_hours = MIN_HOURS_BETWEEN_SHORTS - elapsed
                    print(f"[Safety] Too soon since last short ({elapsed:.1f}h < {MIN_HOURS_BETWEEN_SHORTS}h)")
                    return False, f"Wait {wait_hours:.1f} more hours"
            except Exception:
                pass

    return True, "OK"


def can_upload_long():
    """Check if we can safely upload a Long video"""
    today = get_today_uploads()
    longs_today = [e for e in today if e.get("type") == "long"]

    if longs_today:
        print("[Safety] Already uploaded a long video today")
        return False, "One long video per day maximum"

    this_week = get_this_week_long_uploads()
    if len(this_week) >= 4:
        print(f"[Safety] Weekly long video limit reached (4)")
        return False, "Weekly long video limit (4) reached"

    return True, "OK"


def log_upload_attempt(video_type, success, title):
    log = load_safety_log()
    log.append({
        "type": video_type,
        "title": title[:80],
        "date": datetime.utcnow().isoformat(),
        "success": success,
    })
    if len(log) > 500:
        log = log[-500:]
    save_safety_log(log)


def sanitize_metadata(title, description, tags):
    """Ensure metadata is YouTube ToS compliant"""
    issues = []

    # Title length
    if len(title) > MAX_TITLE_LENGTH:
        title = title[:MAX_TITLE_LENGTH]
        issues.append("Title truncated to 100 chars")

    # Description length
    if len(description) > MAX_DESCRIPTION_LENGTH:
        description = description[:MAX_DESCRIPTION_LENGTH]
        issues.append("Description truncated to 5000 chars")

    # Clean tags
    clean_tags = []
    for tag in (tags or []):
        tag = str(tag).strip()
        if tag and len(tag) <= 500:
            clean_tags.append(tag)

    # Remove duplicate tags
    seen = set()
    unique_tags = []
    for tag in clean_tags:
        normalized = tag.lower()
        if normalized not in seen:
            seen.add(normalized)
            unique_tags.append(tag)

    # No ALL_CAPS spam title
    if title.isupper() and len(title) > 20:
        title = title.title()
        issues.append("Title converted from ALL_CAPS")

    if issues:
        print(f"[Safety] Metadata sanitized: {issues}")

    return title, description, unique_tags


def add_jitter_delay(base_seconds=30, jitter_seconds=60):
    """Add random delay between uploads to appear human-like"""
    delay = base_seconds + random.randint(0, jitter_seconds)
    print(f"[Safety] Adding jitter delay: {delay}s")
    time.sleep(delay)


def check_video_file(video_path):
    """Basic validation of video file before upload"""
    if not os.path.exists(video_path):
        return False, "Video file not found"

    size_mb = os.path.getsize(video_path) / (1024 * 1024)
    if size_mb < 0.1:
        return False, f"Video file too small: {size_mb:.2f} MB"
    if size_mb > 256 * 1024:  # 256 GB YouTube limit
        return False, f"Video file too large: {size_mb:.0f} MB"

    print(f"[Safety] Video file OK: {size_mb:.1f} MB")
    return True, "OK"


def get_safe_posting_time():
    """Get a safe posting time that avoids pattern detection"""
    # Vary posting times significantly
    hour = random.choice([12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22])
    minute = random.choice([0, 5, 11, 17, 23, 30, 37, 42, 51, 58])
    return hour, minute


def get_posting_summary():
    """Summary of today's and this week's posting activity"""
    today = get_today_uploads()
    week = get_this_week_long_uploads()
    return {
        "shorts_today": len([e for e in today if e.get("type") == "short"]),
        "longs_today": len([e for e in today if e.get("type") == "long"]),
        "longs_this_week": len(week),
        "can_post_short": can_upload_short()[0],
        "can_post_long": can_upload_long()[0],
    }


if __name__ == "__main__":
    print(json.dumps(get_posting_summary(), indent=2))
