"""
pipelines/batch_runner.py

Top-level orchestration called by GitHub Actions workflows.

run_production_batch()  — Fill the content buffer (shorts + long) toward
                           growth_rules.content_buffer_targets, bounded by
                           daily_production_target and a hard safety cap.

run_publishing_batch()  — Publish approved items toward today's
                           daily_production_target, respecting the
                           "1 long every ~2 days" cadence.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import structlog

from storage.supabase_client import get_db
from storage.redis_client import get_redis

from pipelines.short_pipeline import get_short_pipeline, PipelineResult
from pipelines.longform_pipeline import get_longform_pipeline
from engines.publisher import get_publisher, PublishResult

logger = structlog.get_logger(__name__)

_DEFAULT_BUFFER_TARGETS = {
    "shorts_minimum": 30, "longs_minimum": 10,
    "emergency_pause_below_shorts": 5, "emergency_pause_below_longs": 2,
}
_DEFAULT_DAILY_TARGET = {"shorts_per_day": 5, "longs_per_two_days": 1, "max_failed_before_alert": 3}

_MAX_SHORTS_PER_RUN = 15   # safety cap on production batch size
_TOPUP_CAP          = 10


@dataclass
class ProductionBatchSummary:
    shorts_attempted: int = 0
    shorts_approved:  int = 0
    shorts_rejected:  int = 0
    shorts_failed:    int = 0
    long_attempted:   bool = False
    long_result:      Optional[str] = None   # "approved" | "rejected" | "failed" | None
    long_quality:     Optional[int] = None
    buffer_before:    Dict[str, int] = field(default_factory=dict)
    buffer_after:     Dict[str, int] = field(default_factory=dict)
    consecutive_failures: int = 0
    halted_reason:    Optional[str] = None
    # Per-failure diagnostic detail — always shown in the Actions log JSON so
    # engineers never have to scroll through thousands of log lines to find
    # the root cause of a halted batch.  Each entry is
    # {"attempt": N, "error": "<message>"}.
    failure_details:  List[Dict] = field(default_factory=list)


@dataclass
class PublishingBatchSummary:
    shorts_published: int = 0
    shorts_skipped:   int = 0
    long_published:   int = 0
    long_skipped:     int = 0
    errors:           List[str] = field(default_factory=list)


class BatchRunner:

    def __init__(self) -> None:
        self._db        = get_db()
        self._redis     = get_redis()
        self._short     = get_short_pipeline()
        self._long      = get_longform_pipeline()
        self._publisher = get_publisher()

    # ═════════════════════════════════════════════════════════════════════════
    # PRODUCTION
    # ═════════════════════════════════════════════════════════════════════════

    def run_production_batch(self) -> ProductionBatchSummary:
        summary = ProductionBatchSummary()
        buffer_targets = self._load_rule("buffer_targets", "content_buffer_targets", _DEFAULT_BUFFER_TARGETS)
        daily_target   = self._load_rule("buffer_targets", "daily_production_target", _DEFAULT_DAILY_TARGET)

        buffer_before = self._safe_buffer_count()
        summary.buffer_before = buffer_before

        shorts_target = self._calc_shorts_to_produce(buffer_before, buffer_targets, daily_target)
        max_failures  = int(daily_target.get("max_failed_before_alert", 3))

        consecutive_failures = 0
        for i in range(shorts_target):
            summary.shorts_attempted += 1
            result = self._safe_run(self._short.run, context="short")

            if result is None or not result.success:
                summary.shorts_failed += 1
                consecutive_failures += 1
                error_msg = (
                    getattr(result, "error", None)
                    or getattr(result, "reason", None)
                    or "unknown error"
                )
                summary.failure_details.append({
                    "attempt": summary.shorts_attempted,
                    "error": str(error_msg)[:400],
                })
            elif result.status == "approved":
                summary.shorts_approved += 1
                consecutive_failures = 0
            elif result.status == "rejected":
                summary.shorts_rejected += 1
                consecutive_failures = 0
            else:
                consecutive_failures += 1

            summary.consecutive_failures = consecutive_failures
            if consecutive_failures >= max_failures:
                summary.halted_reason = (
                    f"halted_after_{consecutive_failures}_consecutive_failures"
                )
                logger.error("production_batch_halted", reason=summary.halted_reason, completed=i + 1)
                break

        # Long-form: only if buffer below target
        longs_minimum = int(buffer_targets.get("longs_minimum", 10))
        if buffer_before.get("longs", 0) < longs_minimum and summary.halted_reason is None:
            summary.long_attempted = True
            long_result = self._safe_run(self._long.run, context="long")
            if long_result is None or not long_result.success:
                summary.long_result = "failed"
            else:
                summary.long_result  = long_result.status
                summary.long_quality = long_result.quality_score

        summary.buffer_after = self._safe_buffer_count()

        logger.info(
            "production_batch_complete",
            attempted=summary.shorts_attempted, approved=summary.shorts_approved,
            rejected=summary.shorts_rejected, failed=summary.shorts_failed,
            long_attempted=summary.long_attempted, long_result=summary.long_result,
            buffer_after=summary.buffer_after,
        )

        try:
            self._redis.heartbeat()
        except Exception:
            pass

        return summary

    def _calc_shorts_to_produce(
        self, buffer: Dict[str, int], buffer_targets: Dict, daily_target: Dict
    ) -> int:
        base = int(daily_target.get("shorts_per_day", 5))
        minimum = int(buffer_targets.get("shorts_minimum", 30))
        current = int(buffer.get("shorts", 0))

        deficit = max(0, minimum - current)
        topup   = min(deficit, _TOPUP_CAP)

        total = base + topup
        return max(1, min(total, _MAX_SHORTS_PER_RUN))

    # ═════════════════════════════════════════════════════════════════════════
    # PUBLISHING
    # ═════════════════════════════════════════════════════════════════════════

    def run_publishing_batch(self) -> PublishingBatchSummary:
        summary = PublishingBatchSummary()
        daily_target = self._load_rule("buffer_targets", "daily_production_target", _DEFAULT_DAILY_TARGET)

        # ── Shorts ───────────────────────────────────────────────────────────
        shorts_per_day   = int(daily_target.get("shorts_per_day", 5))
        shorts_published = self._count_published_today("short")
        remaining_shorts = max(0, shorts_per_day - shorts_published)

        for _ in range(remaining_shorts):
            queue_id = self._next_approved_id("short")
            if queue_id is None:
                summary.shorts_skipped += 1
                break
            result = self._publish_one(queue_id)
            if result.success:
                summary.shorts_published += 1
            else:
                summary.errors.append(f"short:{queue_id[:8]}:{result.error}")
                summary.shorts_skipped += 1

        # ── Long-form (~1 every 2 days) ─────────────────────────────────────
        longs_per_two_days = int(daily_target.get("longs_per_two_days", 1))
        long_published_today     = self._count_published_today("long")
        long_published_yesterday = self._count_published_on_offset("long", days_ago=1)

        should_publish_long = (
            longs_per_two_days >= 1
            and long_published_today == 0
            and long_published_yesterday == 0
        )

        if should_publish_long:
            queue_id = self._next_approved_id("long")
            if queue_id is None:
                summary.long_skipped += 1
            else:
                result = self._publish_one(queue_id)
                if result.success:
                    summary.long_published += 1
                else:
                    summary.errors.append(f"long:{queue_id[:8]}:{result.error}")
                    summary.long_skipped += 1
        else:
            summary.long_skipped += 1

        logger.info(
            "publishing_batch_complete",
            shorts_published=summary.shorts_published, shorts_skipped=summary.shorts_skipped,
            long_published=summary.long_published, long_skipped=summary.long_skipped,
            errors=len(summary.errors),
        )

        try:
            self._redis.heartbeat()
        except Exception:
            pass

        return summary

    def _publish_one(self, queue_id: str) -> PublishResult:
        try:
            return self._publisher.publish(queue_id)
        except Exception as exc:
            logger.error("publish_one_exception", queue_id=queue_id[:8], error=str(exc)[:200])
            return PublishResult(False, error=str(exc)[:200])

    def _next_approved_id(self, video_type: str) -> Optional[str]:
        try:
            rows = self._db.get_approved_queue(video_type=video_type, limit=1)
            return rows[0]["queue_id"] if rows else None
        except Exception as exc:
            logger.warning("approved_queue_fetch_failed", video_type=video_type, error=str(exc)[:100])
            return None

    # ═════════════════════════════════════════════════════════════════════════
    # Internal helpers
    # ═════════════════════════════════════════════════════════════════════════

    def _safe_buffer_count(self) -> Dict[str, int]:
        try:
            return self._db.get_buffer_count()
        except Exception as exc:
            logger.warning("buffer_count_failed", error=str(exc)[:100])
            return {"shorts": 0, "longs": 0}

    def _safe_run(self, fn, context: str) -> Optional[PipelineResult]:
        try:
            return fn()
        except Exception as exc:
            logger.error("pipeline_run_exception", context=context, error=str(exc)[:400])
            # Return a synthetic failed PipelineResult so the batch loop can
            # capture the error message in failure_details without needing a
            # second return path.
            from pipelines.short_pipeline import PipelineResult as PR
            return PR(success=False, status="failed", error=str(exc)[:400])

    def _load_rule(self, category_fallback: str, rule_name: str, default: Dict) -> Dict:
        try:
            rule = self._db.get_rule(rule_name)
            if isinstance(rule, dict) and rule:
                return rule
        except Exception:
            pass
        return dict(default)

    def _count_published_today(self, video_type: str) -> int:
        return self._count_published_on_offset(video_type, days_ago=0)

    def _count_published_on_offset(self, video_type: str, days_ago: int) -> int:
        try:
            recent = self._db.get_recent_published(limit=100)
        except Exception as exc:
            logger.warning("recent_published_fetch_failed", error=str(exc)[:100])
            return 0

        target_date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).date()
        count = 0
        for r in recent:
            if r.get("video_type") != video_type:
                continue
            pub_raw = r.get("published_at", "")
            if not pub_raw:
                continue
            try:
                pub_dt = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if pub_dt.date() == target_date:
                count += 1
        return count


_instance: Optional[BatchRunner] = None

def get_batch_runner() -> BatchRunner:
    global _instance
    if _instance is None:
        _instance = BatchRunner()
    return _instance
