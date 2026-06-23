#!/usr/bin/env python3
"""
scripts/reset_tts_quota.py

Clears the Redis monthly character-quota counters for the ElevenLabs TTS
keys (yta:tts:quota:{key_index}:{YYYY-MM}). Use this to immediately
recover from a false-positive lockout — e.g. one caused by the
now-patched bug where HTTP 402 (voice-accessibility) errors were
incorrectly written into the monthly quota counter, blocking all keys
until end-of-month even though the underlying issue had already been
fixed by the dynamic voice resolver.

Usage
─────
    # Reset all 3 keys for the current month
    python scripts/reset_tts_quota.py

    # Reset a specific key only
    python scripts/reset_tts_quota.py --key 2

    # Reset a specific month (rarely needed)
    python scripts/reset_tts_quota.py --month 2026-06

Requires REDIS_CACHE to be set in the environment (same format as the
main application — see storage/redis_client.py for supported formats).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Running this file directly (`python scripts/reset_tts_quota.py`) sets
# sys.path[0] to this script's own directory (scripts/), NOT the repo
# root — so `storage.redis_client` is never importable no matter what the
# current working directory is. Explicitly add the repo root (this
# script's parent directory) to sys.path so internal imports resolve
# correctly regardless of how this script is invoked: directly, via
# `python -m`, via a GitHub Actions `run:` step, or from any cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset ElevenLabs TTS quota counters in Redis.")
    parser.add_argument(
        "--key", type=int, choices=[1, 2, 3], default=None,
        help="Reset only this key index (1-3). Default: reset all three.",
    )
    parser.add_argument(
        "--month", type=str, default=None,
        help="Target month as YYYY-MM. Default: current UTC month.",
    )
    args = parser.parse_args()

    try:
        from storage.redis_client import get_redis, RK
    except ImportError as exc:
        print(f"ERROR: could not import storage.redis_client — run this from the repo root. {exc}")
        return 1

    month = args.month or datetime.now(timezone.utc).strftime("%Y-%m")
    key_indices = [args.key] if args.key else [1, 2, 3]

    try:
        redis = get_redis()
    except Exception as exc:
        print(f"ERROR: could not connect to Redis. {exc}")
        return 1

    print(f"Resetting TTS quota counters for month={month}, keys={key_indices}\n")

    cleared = 0
    for key_index in key_indices:
        before = redis.get_tts_chars_used(key_index)
        # Use set_tts_chars_used (absolute SET, not INCRBY) so this is
        # idempotent and race-condition-free: if _mark_key_unavailable() fires
        # concurrently in a production run, it now also uses SET 100_000 —
        # the reset's SET 0 wins atomically regardless of ordering, and no
        # leftover INCRBY accumulation can resurrect the block.
        redis.set_tts_chars_used(key_index, 0)
        after = redis.get_tts_chars_used(key_index)
        status = "CLEARED" if before > 0 else "was already 0"
        print(f"  key_index={key_index}  before={before:>7} chars  ->  after={after:>7} chars  [{status}]")
        if before > 0:
            cleared += 1

    print(f"\n{cleared}/{len(key_indices)} counter(s) had data and were cleared.")
    print("Re-run the Daily Production workflow now — affected keys are immediately usable again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
