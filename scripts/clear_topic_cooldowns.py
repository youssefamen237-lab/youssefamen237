#!/usr/bin/env python3
"""
scripts/clear_topic_cooldowns.py

Scans Redis for all yta:dedup:topic:* keys and deletes them, immediately
re-making every topic eligible for selection.

When to run:
  - When Daily Production fails with "No eligible topics found in any category"
  - When topic cooldowns were set during failed runs (the now-fixed bug where
    topic_selector set a 30-day cooldown at selection time rather than at
    confirmed-publish time)
  - After any large batch of failed runs that would have artificially locked out
    topics

Requires: REDIS_CACHE environment variable (same format as the main app)
"""
from __future__ import annotations
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from storage.redis_client import RK, get_redis

_KEY_PATTERN = "yta:dedup:topic:*"


def main() -> int:
    try:
        redis = get_redis()
    except Exception as exc:
        print(f"ERROR: could not connect to Redis. {exc}")
        return 1

    print(f"Scanning for keys matching: {_KEY_PATTERN}\n")

    try:
        keys = list(redis.r.scan_iter(_KEY_PATTERN))
    except Exception as exc:
        print(f"ERROR: Redis SCAN failed. {exc}")
        return 1

    if not keys:
        print("No topic cooldown keys found. Topic pool is already fully open.")
        return 0

    try:
        deleted = redis.r.delete(*keys)
    except Exception as exc:
        print(f"ERROR: Redis DELETE failed. {exc}")
        return 1

    print(f"Deleted {deleted}/{len(keys)} topic cooldown key(s).")
    print("Topic pool is now fully open — all topics are eligible for selection again.")
    print("Re-run Daily Production.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
