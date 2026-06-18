"""
storage/supabase_client.py

Singleton Supabase client — the single source of truth for all database
operations in the YouTube Automation System.  Every engine, pipeline,
and analytics module reads and writes exclusively through this module.

Secret required (GitHub Secret name: SUPABASE):
    Format: {"url": "https://xxxx.supabase.co", "key": "service_role_key"}
"""

from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from supabase import Client, create_client
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Custom exceptions
# ─────────────────────────────────────────────────────────────────────────────

class SupabaseClientError(Exception):
    """Raised when the Supabase client cannot be initialised."""


class RecordNotFoundError(Exception):
    """Raised when an expected database record is absent."""


# ─────────────────────────────────────────────────────────────────────────────
# Singleton client
# ─────────────────────────────────────────────────────────────────────────────

class SupabaseClient:
    """
    Thread-safe singleton that wraps the Supabase Python SDK.
    Provides fully typed, retry-backed methods for all 15 system tables.
    """

    _instance: Optional[SupabaseClient] = None
    _client: Optional[Client] = None
    _initialized: bool = False

    def __new__(cls) -> SupabaseClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._bootstrap()
        self._initialized = True

    # ── Initialisation ────────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        url, key = self._resolve_credentials()
        self._client = create_client(url, key)
        logger.info("supabase_client_ready", host=url.split("//")[-1][:20] + "…")

    @staticmethod
    def _resolve_credentials() -> tuple:
        """
        Resolve Supabase URL + service-role key from env vars.
        Supported formats (tried in order):

        1. JSON string (recommended):
               SUPABASE={"url":"https://xxx.supabase.co","key":"eyJ..."}
        2. Pipe-separated:
               SUPABASE=https://xxx.supabase.co|eyJ...
        3. Two separate variables:
               SUPABASE_URL=https://xxx.supabase.co
               SUPABASE_KEY=eyJ...
        """
        raw = os.getenv("SUPABASE", "").strip()

        # Format 1 — JSON
        if raw and raw.lstrip().startswith("{"):
            try:
                creds: Dict[str, str] = json.loads(raw)
                url = creds.get("url") or creds.get("SUPABASE_URL") or ""
                key = creds.get("key") or creds.get("SUPABASE_KEY") or creds.get("service_role") or ""
                if url and key:
                    return url.strip(), key.strip()
            except json.JSONDecodeError:
                pass

        # Format 2 — pipe-separated  https://xxx.supabase.co|eyJ...
        if raw and "|" in raw:
            parts = raw.split("|", 1)
            if len(parts) == 2 and parts[0].startswith("http"):
                return parts[0].strip(), parts[1].strip()

        # Format 3 — separate SUPABASE_URL + SUPABASE_KEY env vars
        url_env = (
            os.getenv("SUPABASE_URL", "")
            or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
        ).strip()
        key_env = (
            os.getenv("SUPABASE_KEY", "")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
            or os.getenv("SUPABASE_ANON_KEY", "")
        ).strip()
        if url_env and key_env:
            return url_env, key_env

        # Nothing worked — give a precise actionable error
        raise SupabaseClientError(
            "Cannot resolve Supabase credentials.  Set the SUPABASE GitHub Secret to:\n"
            '  {"url": "https://YOUR_PROJECT_REF.supabase.co", "key": "YOUR_SERVICE_ROLE_KEY"}\n'
            "Find both values in: Supabase dashboard → Project Settings → API.\n"
            "Use the service_role key (not the anon key).\n"
            f"Current SUPABASE value length: {len(raw)} chars."
        )

    # ── Core executor with retry ───────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _exec(self, query: Any) -> List[Dict]:
        """Execute any Supabase query builder and return response.data."""
        response = query.execute()
        return response.data or []

    @property
    def client(self) -> Client:
        if self._client is None:  # pragma: no cover
            raise SupabaseClientError("Client not initialised.")
        return self._client

    # ═════════════════════════════════════════════════════════════════════════
    # CHANNEL CONFIG  (table: channel_config)
    # ═════════════════════════════════════════════════════════════════════════

    def get_config(self, key: str) -> Any:
        """Return the JSONB value for a config key, or None if absent."""
        rows = self._exec(
            self.client.table("channel_config")
            .select("config_value")
            .eq("config_key", key)
            .limit(1)
        )
        return rows[0]["config_value"] if rows else None

    def set_config(self, key: str, value: Any) -> None:
        """Upsert a config entry."""
        self._exec(
            self.client.table("channel_config").upsert(
                {
                    "config_key": key,
                    "config_value": value,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="config_key",
            )
        )

    def get_all_config(self) -> Dict[str, Any]:
        """Return every config entry as a flat dict."""
        rows = self._exec(
            self.client.table("channel_config").select("config_key,config_value")
        )
        return {r["config_key"]: r["config_value"] for r in rows}

    # ═════════════════════════════════════════════════════════════════════════
    # GROWTH RULES  (table: growth_rules)
    # ═════════════════════════════════════════════════════════════════════════

    def get_rule(self, rule_name: str) -> Optional[Any]:
        """Return current_value for a named rule, or None."""
        rows = self._exec(
            self.client.table("growth_rules")
            .select("current_value,is_locked")
            .eq("rule_name", rule_name)
            .limit(1)
        )
        return rows[0]["current_value"] if rows else None

    def get_all_rules(self) -> Dict[str, Any]:
        """Return all rules as {rule_name: current_value}."""
        rows = self._exec(
            self.client.table("growth_rules").select("rule_name,current_value")
        )
        return {r["rule_name"]: r["current_value"] for r in rows}

    def update_rule(
        self,
        rule_name: str,
        new_value: Any,
        reason: str,
        updated_by: str = "cos",
    ) -> bool:
        """
        Update a growth rule.  Returns False (silently) if the rule is locked
        or does not exist, so callers do not need to guard the call.
        """
        rows = self._exec(
            self.client.table("growth_rules")
            .select("is_locked,current_value")
            .eq("rule_name", rule_name)
            .limit(1)
        )
        if not rows:
            logger.warning("growth_rule_not_found", rule_name=rule_name)
            return False
        if rows[0]["is_locked"]:
            logger.info("growth_rule_locked_skip", rule_name=rule_name)
            return False

        self._exec(
            self.client.table("growth_rules")
            .update(
                {
                    "previous_value": rows[0]["current_value"],
                    "current_value": new_value,
                    "reason_for_change": reason,
                    "last_updated_by": updated_by,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("rule_name", rule_name)
        )
        logger.info("growth_rule_updated", rule_name=rule_name, by=updated_by)
        return True

    # ═════════════════════════════════════════════════════════════════════════
    # TOPICS  (table: topics)
    # ═════════════════════════════════════════════════════════════════════════

    def get_next_topic(
        self,
        category: Optional[str] = None,
        exclude_ids: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """
        Call the Postgres get_next_topic() function to retrieve the
        highest-value topic that is off cooldown and ready for production.
        """
        params: Dict[str, Any] = {
            "p_exclude_ids": exclude_ids or [],
            "p_category": category,
        }
        rows = self._exec(self.client.rpc("get_next_topic", params))
        return rows[0] if rows else None

    def get_topic_by_id(self, topic_id: str) -> Optional[Dict]:
        rows = self._exec(
            self.client.table("topics").select("*").eq("topic_id", topic_id).limit(1)
        )
        return rows[0] if rows else None

    def update_topic_status(self, topic_id: str, status: str) -> None:
        self._exec(
            self.client.table("topics")
            .update({"status": status})
            .eq("topic_id", topic_id)
        )

    def mark_topic_published(self, topic_id: str, video_type: str) -> None:
        """Stamp last_published_at and increment the appropriate counter."""
        row = self.get_topic_by_id(topic_id)
        if not row:
            return
        counter_field = (
            "shorts_created" if video_type == "short" else "long_videos_created"
        )
        self._exec(
            self.client.table("topics")
            .update(
                {
                    "last_published_at": datetime.now(timezone.utc).isoformat(),
                    counter_field: (row.get(counter_field) or 0) + 1,
                }
            )
            .eq("topic_id", topic_id)
        )

    def update_topic_performance(
        self,
        topic_id: str,
        avg_retention: float,
        avg_ctr: float,
        total_views: int,
    ) -> None:
        self._exec(
            self.client.table("topics")
            .update(
                {
                    "avg_retention": avg_retention,
                    "avg_ctr": avg_ctr,
                    "total_views": total_views,
                }
            )
            .eq("topic_id", topic_id)
        )

    def create_topic(self, data: Dict) -> Dict:
        rows = self._exec(self.client.table("topics").insert(data))
        return rows[0] if rows else {}

    def bulk_insert_topics(self, topics: List[Dict]) -> int:
        """Upsert a batch of topics, ignoring name conflicts.  Returns inserted count."""
        if not topics:
            return 0
        rows = self._exec(
            self.client.table("topics").upsert(topics, on_conflict="topic_name")
        )
        return len(rows)

    def get_topics_by_category(self, category: str, limit: int = 50) -> List[Dict]:
        return self._exec(
            self.client.table("topics_ready_for_production")
            .select("*")
            .eq("category", category)
            .limit(limit)
        )

    # ═════════════════════════════════════════════════════════════════════════
    # FACTS  (table: facts)
    # ═════════════════════════════════════════════════════════════════════════

    def get_facts_for_topic(
        self,
        topic_id: str,
        limit: int = 15,
        min_confidence: int = 70,
    ) -> List[Dict]:
        """Return verified facts for a topic, sorted by curiosity descending."""
        return self._exec(
            self.client.table("facts")
            .select("*")
            .eq("topic_id", topic_id)
            .eq("is_verified", True)
            .in_("status", ["new", "verified", "gold"])
            .gte("confidence_score", min_confidence)
            .order("curiosity_level", desc=True)
            .limit(limit)
        )

    def create_fact(self, data: Dict) -> Dict:
        rows = self._exec(self.client.table("facts").insert(data))
        return rows[0] if rows else {}

    def bulk_insert_facts(self, facts: List[Dict]) -> int:
        if not facts:
            return 0
        rows = self._exec(self.client.table("facts").insert(facts))
        return len(rows)

    def mark_fact_used(self, fact_id: str) -> None:
        rows = self._exec(
            self.client.table("facts")
            .select("usage_count")
            .eq("fact_id", fact_id)
            .limit(1)
        )
        current = rows[0]["usage_count"] if rows else 0
        self._exec(
            self.client.table("facts")
            .update({"status": "used", "usage_count": current + 1})
            .eq("fact_id", fact_id)
        )

    def mark_fact_gold(self, fact_id: str) -> None:
        self._exec(
            self.client.table("facts")
            .update({"is_gold": True, "status": "gold"})
            .eq("fact_id", fact_id)
        )

    # ═════════════════════════════════════════════════════════════════════════
    # SOURCES  (table: sources)
    # ═════════════════════════════════════════════════════════════════════════

    def get_active_sources(
        self, specialization: Optional[str] = None
    ) -> List[Dict]:
        query = (
            self.client.table("sources")
            .select("*")
            .eq("is_active", True)
            .order("trust_score", desc=True)
        )
        if specialization:
            query = query.contains("specializations", [specialization])
        return self._exec(query)

    def get_source_by_name(self, name: str) -> Optional[Dict]:
        rows = self._exec(
            self.client.table("sources").select("*").eq("source_name", name).limit(1)
        )
        return rows[0] if rows else None

    def record_source_verification(self, source_id: str, success: bool) -> None:
        rows = self._exec(
            self.client.table("sources")
            .select("successful_verifications,failed_verifications,fact_count")
            .eq("source_id", source_id)
            .limit(1)
        )
        if not rows:
            return
        row = rows[0]
        update: Dict[str, Any] = {
            "last_used_at": datetime.now(timezone.utc).isoformat(),
        }
        if success:
            update["successful_verifications"] = (row.get("successful_verifications") or 0) + 1
            update["fact_count"] = (row.get("fact_count") or 0) + 1
        else:
            update["failed_verifications"] = (row.get("failed_verifications") or 0) + 1
        self._exec(
            self.client.table("sources").update(update).eq("source_id", source_id)
        )

    # ═════════════════════════════════════════════════════════════════════════
    # HOOKS  (table: hooks)
    # ═════════════════════════════════════════════════════════════════════════

    def get_hooks_by_type(
        self,
        hook_type: str,
        exclude_ids: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict]:
        exclude_ids = exclude_ids or []
        query = (
            self.client.table("hooks")
            .select("*")
            .eq("hook_type", hook_type)
            .eq("is_banned", False)
            .order("avg_retention", desc=True)
            .limit(limit)
        )
        rows = self._exec(query)
        if exclude_ids:
            rows = [r for r in rows if r["hook_id"] not in exclude_ids]
        return rows

    def increment_hook_usage(self, hook_id: str) -> None:
        rows = self._exec(
            self.client.table("hooks")
            .select("usage_count")
            .eq("hook_id", hook_id)
            .limit(1)
        )
        current = rows[0]["usage_count"] if rows else 0
        self._exec(
            self.client.table("hooks")
            .update({"usage_count": current + 1})
            .eq("hook_id", hook_id)
        )

    def update_hook_performance(
        self, hook_id: str, avg_ctr: float, avg_retention: float
    ) -> None:
        self._exec(
            self.client.table("hooks")
            .update({"avg_ctr": avg_ctr, "avg_retention": avg_retention})
            .eq("hook_id", hook_id)
        )

    # ═════════════════════════════════════════════════════════════════════════
    # TITLES  (table: titles)
    # ═════════════════════════════════════════════════════════════════════════

    def get_titles_by_type(
        self,
        title_type: str,
        limit: int = 5,
    ) -> List[Dict]:
        return self._exec(
            self.client.table("titles")
            .select("*")
            .eq("title_type", title_type)
            .eq("is_banned", False)
            .order("avg_ctr", desc=True)
            .limit(limit)
        )

    def mark_title_used(self, title_id: str) -> None:
        rows = self._exec(
            self.client.table("titles")
            .select("usage_count")
            .eq("title_id", title_id)
            .limit(1)
        )
        current = rows[0]["usage_count"] if rows else 0
        self._exec(
            self.client.table("titles")
            .update(
                {
                    "usage_count": current + 1,
                    "last_used_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("title_id", title_id)
        )

    # ═════════════════════════════════════════════════════════════════════════
    # CTAs  (table: ctas)
    # ═════════════════════════════════════════════════════════════════════════

    def get_random_cta(
        self,
        cta_type: Optional[str] = None,
        exclude_ids: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        exclude_ids = exclude_ids or []
        query = (
            self.client.table("ctas").select("*").eq("is_banned", False).limit(50)
        )
        if cta_type:
            query = query.eq("cta_type", cta_type)
        rows = self._exec(query)
        available = [r for r in rows if r["cta_id"] not in exclude_ids]
        return random.choice(available) if available else None

    def increment_cta_usage(self, cta_id: str) -> None:
        rows = self._exec(
            self.client.table("ctas")
            .select("usage_count")
            .eq("cta_id", cta_id)
            .limit(1)
        )
        current = rows[0]["usage_count"] if rows else 0
        self._exec(
            self.client.table("ctas")
            .update({"usage_count": current + 1})
            .eq("cta_id", cta_id)
        )

    # ═════════════════════════════════════════════════════════════════════════
    # MUSIC  (table: music_tracks)
    # ═════════════════════════════════════════════════════════════════════════

    def get_music_track(
        self, category: str, mood: Optional[str] = None
    ) -> Optional[Dict]:
        """Return a random active, downloaded track for the given category."""
        query = (
            self.client.table("music_tracks")
            .select("*")
            .eq("category", category)
            .eq("is_active", True)
            .eq("is_downloaded", True)
            .limit(20)
        )
        if mood:
            query = query.eq("mood", mood)
        rows = self._exec(query)
        if not rows:
            # Fallback to 'general' category
            rows = self._exec(
                self.client.table("music_tracks")
                .select("*")
                .eq("category", "general")
                .eq("is_active", True)
                .eq("is_downloaded", True)
                .limit(10)
            )
        return random.choice(rows) if rows else None

    def mark_music_downloaded(self, track_id: str, r2_path: str) -> None:
        self._exec(
            self.client.table("music_tracks")
            .update({"is_downloaded": True, "r2_path": r2_path})
            .eq("track_id", track_id)
        )

    # ═════════════════════════════════════════════════════════════════════════
    # VIDEO QUEUE  (table: video_queue)
    # ═════════════════════════════════════════════════════════════════════════

    def create_video_job(
        self,
        topic_id: str,
        video_type: str,
        priority: int = 5,
        voice_gender: Optional[str] = None,
    ) -> Dict:
        """Create a new production job.  Returns the created row."""
        payload: Dict[str, Any] = {
            "topic_id": topic_id,
            "video_type": video_type,
            "status": "pending",
            "priority": priority,
        }
        if voice_gender:
            payload["voice_gender"] = voice_gender
        rows = self._exec(self.client.table("video_queue").insert(payload))
        return rows[0] if rows else {}

    def get_video_job(self, queue_id: str) -> Optional[Dict]:
        rows = self._exec(
            self.client.table("video_queue")
            .select("*")
            .eq("queue_id", queue_id)
            .limit(1)
        )
        return rows[0] if rows else None

    def update_video_status(
        self,
        queue_id: str,
        status: str,
        extra: Optional[Dict] = None,
    ) -> None:
        """
        Update the status of a video job.
        Pass extra={field: value, ...} to simultaneously update other columns.
        """
        payload: Dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            payload.update(extra)
        self._exec(
            self.client.table("video_queue").update(payload).eq("queue_id", queue_id)
        )
        logger.debug("job_status_updated", queue_id=queue_id[:8], status=status)

    def log_job_error(self, queue_id: str, step: str, error: str) -> None:
        """Append an error entry to error_log and increment retry_count."""
        job = self.get_video_job(queue_id)
        if not job:
            return
        error_log: List[Dict] = job.get("error_log") or []
        error_log.append(
            {
                "step": step,
                "error": error,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        retry_count = (job.get("retry_count") or 0) + 1
        new_status = "failed" if retry_count >= 3 else job["status"]
        self._exec(
            self.client.table("video_queue")
            .update(
                {
                    "error_log": error_log,
                    "retry_count": retry_count,
                    "status": new_status,
                }
            )
            .eq("queue_id", queue_id)
        )

    def get_approved_queue(
        self, video_type: Optional[str] = None, limit: int = 10
    ) -> List[Dict]:
        """Return approved jobs ready for publishing, highest priority first."""
        query = (
            self.client.table("video_queue")
            .select("*")
            .eq("status", "approved")
            .order("priority", desc=True)
            .order("created_at", desc=False)
            .limit(limit)
        )
        if video_type:
            query = query.eq("video_type", video_type)
        return self._exec(query)

    def get_buffer_count(self) -> Dict[str, int]:
        """Return current approved buffer counts per video type."""
        rows = self._exec(
            self.client.table("video_queue")
            .select("video_type")
            .eq("status", "approved")
        )
        shorts = sum(1 for r in rows if r["video_type"] == "short")
        longs = sum(1 for r in rows if r["video_type"] == "long")
        return {"shorts": shorts, "longs": longs}

    def get_queue_stats(self) -> Dict[str, int]:
        """Return job counts grouped by status."""
        rows = self._exec(self.client.table("video_queue").select("status"))
        stats: Dict[str, int] = {}
        for r in rows:
            s = r["status"]
            stats[s] = stats.get(s, 0) + 1
        return stats

    # ═════════════════════════════════════════════════════════════════════════
    # PUBLISHED LOG  (table: published_log)
    # ═════════════════════════════════════════════════════════════════════════

    def insert_published_record(self, data: Dict) -> Dict:
        rows = self._exec(self.client.table("published_log").insert(data))
        return rows[0] if rows else {}

    def get_published_today(self) -> int:
        today = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        rows = self._exec(
            self.client.table("published_log")
            .select("log_id")
            .gte("published_at", today.isoformat())
        )
        return len(rows)

    def get_recent_published(self, limit: int = 100) -> List[Dict]:
        return self._exec(
            self.client.table("published_log")
            .select("*")
            .order("published_at", desc=True)
            .limit(limit)
        )

    def get_published_by_youtube_id(self, yt_id: str) -> Optional[Dict]:
        rows = self._exec(
            self.client.table("published_log")
            .select("*")
            .eq("youtube_video_id", yt_id)
            .limit(1)
        )
        return rows[0] if rows else None

    # ═════════════════════════════════════════════════════════════════════════
    # PERFORMANCE METRICS  (table: performance_metrics)
    # ═════════════════════════════════════════════════════════════════════════

    def upsert_metrics(self, youtube_video_id: str, metrics: Dict) -> None:
        self._exec(
            self.client.table("performance_metrics").insert(
                {"youtube_video_id": youtube_video_id, **metrics}
            )
        )

    def get_latest_metrics(self, youtube_video_id: str) -> Optional[Dict]:
        rows = self._exec(
            self.client.table("performance_metrics")
            .select("*")
            .eq("youtube_video_id", youtube_video_id)
            .order("recorded_at", desc=True)
            .limit(1)
        )
        return rows[0] if rows else None

    def get_category_performance_summary(self) -> List[Dict]:
        """Query the category_performance_summary view."""
        return self._exec(
            self.client.table("category_performance_summary").select("*")
        )

    # ═════════════════════════════════════════════════════════════════════════
    # LEARNING MEMORY  (table: learning_memory)
    # ═════════════════════════════════════════════════════════════════════════

    def upsert_memory(
        self,
        memory_type: str,
        memory_key: str,
        memory_value: Any,
        confidence: float = 50.0,
        data_points: int = 1,
    ) -> None:
        existing = self.get_memory(memory_type, memory_key)
        if existing:
            new_dp = (existing.get("data_points") or 1) + data_points
            self._exec(
                self.client.table("learning_memory")
                .update(
                    {
                        "memory_value": memory_value,
                        "confidence": confidence,
                        "data_points": new_dp,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                .eq("memory_type", memory_type)
                .eq("memory_key", memory_key)
            )
        else:
            self._exec(
                self.client.table("learning_memory").insert(
                    {
                        "memory_type": memory_type,
                        "memory_key": memory_key,
                        "memory_value": memory_value,
                        "confidence": confidence,
                        "data_points": data_points,
                    }
                )
            )

    def get_memory(self, memory_type: str, memory_key: str) -> Optional[Dict]:
        rows = self._exec(
            self.client.table("learning_memory")
            .select("*")
            .eq("memory_type", memory_type)
            .eq("memory_key", memory_key)
            .eq("is_active", True)
            .limit(1)
        )
        return rows[0] if rows else None

    def get_all_memories_by_type(self, memory_type: str) -> List[Dict]:
        return self._exec(
            self.client.table("learning_memory")
            .select("*")
            .eq("memory_type", memory_type)
            .eq("is_active", True)
            .order("confidence", desc=True)
        )

    # ═════════════════════════════════════════════════════════════════════════
    # VISUAL ASSETS  (table: visual_assets)
    # ═════════════════════════════════════════════════════════════════════════

    def find_verified_asset(
        self, topic_tags: List[str], asset_type: str = "video"
    ) -> Optional[Dict]:
        """
        Look for a previously verified clip that matches any of the given tags.
        Returns the highest visual_match_score result.
        """
        rows = self._exec(
            self.client.table("visual_assets")
            .select("*")
            .contains("topic_tags", topic_tags)
            .eq("asset_type", asset_type)
            .eq("has_watermark", False)
            .order("visual_match_score", desc=True)
            .limit(1)
        )
        return rows[0] if rows else None

    def register_asset(self, asset_data: Dict) -> Optional[Dict]:
        """Register a newly verified clip.  Ignores duplicate file hashes."""
        rows = self._exec(
            self.client.table("visual_assets").upsert(
                asset_data, on_conflict="file_hash"
            )
        )
        return rows[0] if rows else None

    def increment_asset_usage(self, asset_id: str) -> None:
        rows = self._exec(
            self.client.table("visual_assets")
            .select("usage_count")
            .eq("asset_id", asset_id)
            .limit(1)
        )
        current = rows[0]["usage_count"] if rows else 0
        self._exec(
            self.client.table("visual_assets")
            .update(
                {
                    "usage_count": current + 1,
                    "last_used_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("asset_id", asset_id)
        )

    # ═════════════════════════════════════════════════════════════════════════
    # COMPETITORS  (table: competitors)
    # ═════════════════════════════════════════════════════════════════════════

    def get_active_competitors(self) -> List[Dict]:
        return self._exec(
            self.client.table("competitors")
            .select("*")
            .eq("is_active", True)
            .order("subscriber_count", desc=True)
        )

    def upsert_competitor(self, data: Dict) -> Dict:
        rows = self._exec(
            self.client.table("competitors").upsert(data, on_conflict="channel_name")
        )
        return rows[0] if rows else {}

    # ═════════════════════════════════════════════════════════════════════════
    # WAR ROOM  (view: channel_war_room)
    # ═════════════════════════════════════════════════════════════════════════

    def get_war_room_snapshot(self) -> Dict:
        """Single-query executive dashboard from the channel_war_room view."""
        rows = self._exec(
            self.client.table("channel_war_room").select("*").limit(1)
        )
        return rows[0] if rows else {}

    def get_queue_health(self) -> Dict:
        """
        Call the get_queue_health() Postgres function.
        This function RETURNS JSONB (scalar), so PostgREST returns the
        object directly rather than wrapping it in an array — unlike
        RETURNS TABLE functions such as get_next_topic().
        """
        result = self._exec(self.client.rpc("get_queue_health", {}))
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and result:
            first = result[0]
            return first if isinstance(first, dict) else {}
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Module-level accessor — use this everywhere instead of SupabaseClient()
# ─────────────────────────────────────────────────────────────────────────────

_db_instance: Optional[SupabaseClient] = None


def get_db() -> SupabaseClient:
    """Return the process-level singleton SupabaseClient."""
    global _db_instance
    if _db_instance is None:
        _db_instance = SupabaseClient()
    return _db_instance
