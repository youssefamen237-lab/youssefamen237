"""
bootstrap/initial_setup.py

One-time (idempotent) system initialization.
Run via: python -m bootstrap.initial_setup [--force]
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from typing import Any, Dict
import structlog

from storage.supabase_client import get_db
from storage.redis_client import get_redis
from storage.r2_client import get_r2
from data.seeds import seed_topics, seed_music

logger = structlog.get_logger(__name__)


def run(force: bool = False) -> Dict[str, Any]:
    db = get_db()
    summary: Dict[str, Any] = {"already_initialized": False}

    if not force:
        existing = db.get_config("initialized_at")
        if existing:
            summary["already_initialized"] = True
            summary["initialized_at"] = existing
            logger.info("bootstrap_already_done", initialized_at=existing)
            return summary

    # ── Health checks ─────────────────────────────────────────────────────────
    summary["redis_ok"]  = _safe(lambda: bool(get_redis().ping()), False)
    summary["r2_bucket"] = _safe(lambda: get_r2().bucket, "unknown")
    summary["war_room"]  = _safe(lambda: db.get_war_room_snapshot(), {})

    # ── Seeding ───────────────────────────────────────────────────────────────
    summary["topics"] = _safe(lambda: seed_topics.seed_all(), {})
    summary["music"]  = _safe(lambda: seed_music.seed_all(), {})

    now_iso = datetime.now(timezone.utc).isoformat()
    db.set_config("initialized_at", now_iso)
    summary["initialized_at"] = now_iso

    logger.info(
        "bootstrap_complete",
        redis_ok=summary["redis_ok"],
        r2_bucket=summary["r2_bucket"],
        topics_total=sum(summary["topics"].values()) if summary["topics"] else 0,
        music_inserted=summary["music"].get("inserted", 0) if summary["music"] else 0,
    )
    return summary


def _safe(fn, default: Any) -> Any:
    try:
        return fn()
    except Exception as exc:
        logger.warning("bootstrap_step_failed", error=str(exc)[:150])
        return default


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap the YouTube Automation System.")
    parser.add_argument("--force", action="store_true",
                         help="Re-run seeding even if already initialized.")
    args = parser.parse_args()

    result = run(force=args.force)

    print("\n=== Bootstrap Summary ===")
    print(f"  already_initialized : {result.get('already_initialized')}")
    print(f"  initialized_at      : {result.get('initialized_at')}")
    if "redis_ok" in result:
        print(f"  redis_ok            : {result['redis_ok']}")
        print(f"  r2_bucket           : {result['r2_bucket']}")
        print(f"  topics              : {result['topics']}")
        print(f"  music               : {result['music']}")
