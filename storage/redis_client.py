"""
storage/redis_client.py

Singleton Redis client backed by Upstash.
Covers every real-time coordination need of the system:

  • API quota tracking   — ElevenLabs (per key), YouTube uploads (per key)
  • Deduplication        — script hash, title hash, topic cooldown
  • Job locking          — prevent duplicate production runs
  • Voice rotation state — enforce gender/voice-ID consecutive limits
  • Hook recency         — sliding window of recently used hooks
  • System health        — Dead Man's Switch heartbeat
  • Cache                — growth rules, channel config (1-hour TTL)

Required GitHub Secret
──────────────────────
  REDIS_CACHE    Upstash connection URL
                 Format: rediss://default:<password>@<host>.upstash.io:<port>
"""

from __future__ import annotations

import json
import logging
import os
import time
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

import redis
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Namespaced key templates
# ─────────────────────────────────────────────────────────────────────────────

class RK:
    """
    Redis Key (RK) — canonical templates for every key used in the system.
    All keys are prefixed with 'yta:' (YouTube Automation) to avoid collisions
    if the Upstash instance is shared.
    """

    # ── API quota ──────────────────────────────────────────────────────────────
    # Resets monthly (ElevenLabs) or daily (YouTube)
    TTS_QUOTA        = "yta:quota:tts:{key_index}:{month}"       # chars used
    YT_UPLOAD_QUOTA  = "yta:quota:yt_upload:{key_index}:{date}"  # API units used
    YT_MGMT_QUOTA    = "yta:quota:yt_mgmt:{date}"                # management key units

    # ── Deduplication ─────────────────────────────────────────────────────────
    SCRIPT_HASH      = "yta:dedup:script:{hash}"                 # TTL = 90 days
    TITLE_HASH       = "yta:dedup:title:{hash}"                  # TTL = 60 days
    TOPIC_COOLDOWN   = "yta:dedup:topic:{topic_id}"              # TTL = cooldown_days

    # ── Job locking ───────────────────────────────────────────────────────────
    JOB_LOCK         = "yta:lock:job:{queue_id}"                 # TTL = 1 hour
    PROD_LOCK        = "yta:lock:prod:{video_type}"              # TTL = 2 hours

    # ── Voice rotation state ──────────────────────────────────────────────────
    VOICE_STATE      = "yta:voice:state"                          # no TTL

    # ── Hook recency (sorted set: hook_id → unix timestamp) ───────────────────
    HOOKS_RECENT     = "yta:hooks:recent"                         # no TTL

    # ── System health / Dead Man's Switch ────────────────────────────────────
    SYSTEM_HEALTH    = "yta:system:health"                        # TTL = 6 hours
    LAST_PUBLISH     = "yta:system:last_publish:{video_type}"

    # ── Cache ─────────────────────────────────────────────────────────────────
    GROWTH_RULES     = "yta:cache:growth_rules"                   # TTL = 1 hour
    CHANNEL_CONFIG   = "yta:cache:channel_config"                 # TTL = 1 hour
    WAR_ROOM         = "yta:cache:war_room"                       # TTL = 5 min

    # ─────────────────────────────────────────────────────────────────────────
    # Builder helpers
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def tts_quota(cls, key_index: int, month: Optional[str] = None) -> str:
        if month is None:
            month = datetime.utcnow().strftime("%Y-%m")
        return cls.TTS_QUOTA.format(key_index=key_index, month=month)

    @classmethod
    def yt_upload_quota(cls, key_index: int, date: Optional[str] = None) -> str:
        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")
        return cls.YT_UPLOAD_QUOTA.format(key_index=key_index, date=date)

    @classmethod
    def yt_mgmt_quota(cls, date: Optional[str] = None) -> str:
        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")
        return cls.YT_MGMT_QUOTA.format(date=date)

    @classmethod
    def script_hash(cls, text: str) -> str:
        h = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:32]
        return cls.SCRIPT_HASH.format(hash=h)

    @classmethod
    def title_hash(cls, title: str) -> str:
        h = hashlib.sha256(title.lower().strip().encode()).hexdigest()[:32]
        return cls.TITLE_HASH.format(hash=h)

    @classmethod
    def topic_cooldown(cls, topic_id: str) -> str:
        return cls.TOPIC_COOLDOWN.format(topic_id=topic_id)

    @classmethod
    def job_lock(cls, queue_id: str) -> str:
        return cls.JOB_LOCK.format(queue_id=queue_id)

    @classmethod
    def prod_lock(cls, video_type: str) -> str:
        return cls.PROD_LOCK.format(video_type=video_type)

    @classmethod
    def last_publish(cls, video_type: str) -> str:
        return cls.LAST_PUBLISH.format(video_type=video_type)


# ─────────────────────────────────────────────────────────────────────────────
# Singleton client
# ─────────────────────────────────────────────────────────────────────────────

class RedisClient:
    """
    Thread-safe singleton Redis client (Upstash / any standard Redis).
    All real-time coordination in the system routes through this class.
    """

    _instance: Optional[RedisClient] = None
    _redis: Optional[redis.Redis] = None
    _initialized: bool = False

    def __new__(cls) -> RedisClient:
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
        url = self._resolve_redis_url()
        self._redis = redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=10,
            socket_timeout=10,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        self._redis.ping()
        host = url.split("@")[-1].split(":")[0] if "@" in url else "unknown"
        logger.info("redis_client_ready", host=host[:20] + "…")

    @staticmethod
    def _resolve_redis_url() -> str:
        """
        Resolve a valid redis:// or rediss:// URL from REDIS_CACHE.

        Supported formats (tried in order):

        1. Full URL already valid:
               REDIS_CACHE=rediss://default:PASSWORD@host.upstash.io:6379

        2. Upstash REST URL accidentally pasted instead of Redis URL:
               REDIS_CACHE=https://host.upstash.io  (auto-converted)

        3. Host + password as JSON:
               REDIS_CACHE={"host":"host.upstash.io","password":"xxx","port":6379}

        4. Pipe-separated host|password:
               REDIS_CACHE=host.upstash.io|PASSWORD
        """
        raw = os.getenv("REDIS_CACHE", "").strip()
        if not raw:
            raise ValueError(
                "REDIS_CACHE environment variable is not set.\n"
                "Set it to your Upstash Redis URL — found in:\n"
                "  Upstash console → your database → Connect → Redis URL\n"
                "Format: rediss://default:PASSWORD@HOST.upstash.io:6379"
            )

        # Format 1 — already a valid redis URL
        if raw.startswith(("redis://", "rediss://", "unix://")):
            return raw

        # Format 2 — Upstash HTTPS REST URL accidentally used instead of Redis URL
        # e.g. https://YOUR-ENDPOINT.upstash.io
        if raw.startswith("https://") and "upstash.io" in raw:
            raise ValueError(
                "REDIS_CACHE looks like an Upstash REST URL (https://...), "
                "but a Redis connection URL is required.\n"
                "In the Upstash console → your database → Connect tab → "
                "copy the value labelled 'Redis URL' (starts with rediss://)."
            )

        # Format 3 — JSON {"host":..., "password":..., "port":...}
        if raw.startswith("{"):
            try:
                import json as _json
                d = _json.loads(raw)
                host = d.get("host") or d.get("endpoint") or ""
                password = d.get("password") or d.get("token") or ""
                port = int(d.get("port", 6379))
                if host and password:
                    return f"rediss://default:{password}@{host}:{port}"
            except Exception:
                pass

        # Format 4 — pipe-separated  host.upstash.io|PASSWORD
        if "|" in raw:
            parts = raw.split("|", 1)
            if len(parts) == 2:
                host, password = parts[0].strip(), parts[1].strip()
                port = 6379
                if ":" in host:
                    host, port_str = host.rsplit(":", 1)
                    port = int(port_str)
                return f"rediss://default:{password}@{host}:{port}"

        raise ValueError(
            f"Cannot parse REDIS_CACHE value (length {len(raw)}).\n"
            "Set it to your Upstash Redis connection URL:\n"
            "  Upstash console → your database → Connect → Redis URL\n"
            "Format: rediss://default:PASSWORD@HOST.upstash.io:6379"
        )

    @property
    def r(self) -> redis.Redis:
        if self._redis is None:  # pragma: no cover
            raise RuntimeError("Redis client not initialised.")
        return self._redis

    # ═════════════════════════════════════════════════════════════════════════
    # API QUOTA MANAGEMENT
    # ═════════════════════════════════════════════════════════════════════════

    # ── ElevenLabs TTS ────────────────────────────────────────────────────────

    def get_tts_chars_used(self, key_index: int) -> int:
        """Return characters consumed by a TTS key this calendar month."""
        val = self.r.get(RK.tts_quota(key_index))
        return int(val) if val else 0

    def add_tts_chars_used(self, key_index: int, char_count: int) -> int:
        """Atomically add char_count to a TTS key's monthly usage. Returns new total."""
        rkey = RK.tts_quota(key_index)
        pipe = self.r.pipeline(transaction=True)
        pipe.incrby(rkey, char_count)
        pipe.expireat(rkey, self._end_of_month_unix())
        results = pipe.execute()
        return int(results[0])

    def get_best_tts_key(
        self,
        monthly_limit: int = 100_000,
        char_count_needed: int = 500,
    ) -> Optional[int]:
        """
        Return the key index (1, 2, or 3) with the most remaining TTS chars.
        Returns None if all keys are exhausted for the month.
        Also falls back to key index 0 which represents the free edge-tts fallback.
        """
        best_key: Optional[int] = None
        best_remaining: int = -1

        for idx in [1, 2, 3]:
            used = self.get_tts_chars_used(idx)
            remaining = monthly_limit - used
            if remaining >= char_count_needed and remaining > best_remaining:
                best_remaining = remaining
                best_key = idx

        if best_key is None:
            logger.warning("all_tts_keys_exhausted_falling_back_to_edge_tts")
        return best_key  # None → caller must use edge-tts

    # ── YouTube Upload Quota ───────────────────────────────────────────────────

    def get_yt_upload_units_used(self, key_index: int) -> int:
        """Return YouTube upload quota units consumed by a key today."""
        val = self.r.get(RK.yt_upload_quota(key_index))
        return int(val) if val else 0

    def add_yt_upload_units(self, key_index: int, units: int = 1_600) -> int:
        """Add units to a YT upload key's daily quota.  Returns new total."""
        rkey = RK.yt_upload_quota(key_index)
        pipe = self.r.pipeline(transaction=True)
        pipe.incrby(rkey, units)
        pipe.expire(rkey, 172_800)   # 2-day TTL (covers timezone edge cases)
        results = pipe.execute()
        return int(results[0])

    def get_best_yt_upload_key(
        self,
        units_per_upload: int = 1_600,
        daily_limit: int = 9_000,
    ) -> Optional[int]:
        """
        Return the upload key index (1, 2, or 3) with the most remaining quota.
        Returns None if all 3 keys are exhausted.
        """
        best_key: Optional[int] = None
        best_remaining: int = -1

        for idx in [1, 2, 3]:
            used = self.get_yt_upload_units_used(idx)
            remaining = daily_limit - used
            if remaining >= units_per_upload and remaining > best_remaining:
                best_remaining = remaining
                best_key = idx

        if best_key is None:
            logger.warning("all_yt_upload_keys_exhausted_for_today")
        return best_key

    # ── YouTube Management Quota ───────────────────────────────────────────────

    def get_yt_mgmt_units_used(self) -> int:
        val = self.r.get(RK.yt_mgmt_quota())
        return int(val) if val else 0

    def add_yt_mgmt_units(self, units: int) -> int:
        rkey = RK.yt_mgmt_quota()
        pipe = self.r.pipeline(transaction=True)
        pipe.incrby(rkey, units)
        pipe.expire(rkey, 172_800)
        results = pipe.execute()
        return int(results[0])

    # ═════════════════════════════════════════════════════════════════════════
    # DEDUPLICATION
    # ═════════════════════════════════════════════════════════════════════════

    def is_script_duplicate(self, script_text: str) -> bool:
        """True if a script with this content fingerprint was produced recently."""
        return bool(self.r.exists(RK.script_hash(script_text)))

    def register_script(self, script_text: str, ttl_days: int = 90) -> None:
        """Mark a script fingerprint as seen for ttl_days days."""
        self.r.setex(RK.script_hash(script_text), ttl_days * 86_400, "1")

    def is_title_duplicate(self, title: str) -> bool:
        """True if this exact title (case-insensitive) was used recently."""
        return bool(self.r.exists(RK.title_hash(title)))

    def register_title(self, title: str, ttl_days: int = 60) -> None:
        self.r.setex(RK.title_hash(title), ttl_days * 86_400, "1")

    def is_topic_on_cooldown(self, topic_id: str) -> bool:
        """True if the topic's cooldown period has not yet expired in Redis."""
        return bool(self.r.exists(RK.topic_cooldown(topic_id)))

    def set_topic_cooldown(self, topic_id: str, cooldown_days: int) -> None:
        self.r.setex(RK.topic_cooldown(topic_id), cooldown_days * 86_400, "1")

    def clear_topic_cooldown(self, topic_id: str) -> None:
        """Force-clear a topic's cooldown (e.g. after an admin override)."""
        self.r.delete(RK.topic_cooldown(topic_id))

    # ═════════════════════════════════════════════════════════════════════════
    # JOB LOCKING  (prevent duplicate parallel production)
    # ═════════════════════════════════════════════════════════════════════════

    def acquire_job_lock(self, queue_id: str, ttl_seconds: int = 3_600) -> bool:
        """
        Atomically acquire an exclusive lock for a production job.
        Returns True if the lock was acquired (i.e. not already held).
        """
        result = self.r.set(RK.job_lock(queue_id), "1", nx=True, ex=ttl_seconds)
        return result is True

    def release_job_lock(self, queue_id: str) -> None:
        self.r.delete(RK.job_lock(queue_id))

    def acquire_production_lock(
        self, video_type: str, ttl_seconds: int = 7_200
    ) -> bool:
        """
        Prevent two concurrent pipeline runs of the same video type.
        Returns True if lock was acquired.
        """
        result = self.r.set(
            RK.prod_lock(video_type), "1", nx=True, ex=ttl_seconds
        )
        return result is True

    def release_production_lock(self, video_type: str) -> None:
        self.r.delete(RK.prod_lock(video_type))

    def extend_job_lock(self, queue_id: str, extra_seconds: int = 1_800) -> None:
        """Extend an existing job lock TTL (call mid-pipeline for long tasks)."""
        self.r.expire(RK.job_lock(queue_id), extra_seconds)

    # ═════════════════════════════════════════════════════════════════════════
    # VOICE ROTATION STATE
    # ═════════════════════════════════════════════════════════════════════════

    def get_voice_state(self) -> Dict[str, Any]:
        """
        Return the current voice rotation state dict.
        Keys: last_gender, last_voice_id, female_consecutive,
              male_consecutive, voice_id_consecutive.
        """
        raw = self.r.get(RK.VOICE_STATE)
        if raw:
            return json.loads(raw)
        return {
            "last_gender": None,
            "last_voice_id": None,
            "female_consecutive": 0,
            "male_consecutive": 0,
            "voice_id_consecutive": 0,
        }

    def update_voice_state(self, gender: str, voice_id: str) -> Dict[str, Any]:
        """
        Update rotation counters after a voice is selected.
        Returns the new state dict.
        """
        state = self.get_voice_state()

        if gender == "female":
            state["female_consecutive"] = (state.get("female_consecutive") or 0) + 1
            state["male_consecutive"] = 0
        else:
            state["male_consecutive"] = (state.get("male_consecutive") or 0) + 1
            state["female_consecutive"] = 0

        if state.get("last_voice_id") == voice_id:
            state["voice_id_consecutive"] = (state.get("voice_id_consecutive") or 0) + 1
        else:
            state["voice_id_consecutive"] = 1

        state["last_gender"] = gender
        state["last_voice_id"] = voice_id

        self.r.set(RK.VOICE_STATE, json.dumps(state))
        return state

    def reset_voice_state(self) -> None:
        """Full reset — use only in tests or after a manual override."""
        self.r.delete(RK.VOICE_STATE)

    # ═════════════════════════════════════════════════════════════════════════
    # HOOK RECENCY  (sorted set, score = unix timestamp)
    # ═════════════════════════════════════════════════════════════════════════

    def mark_hook_used(self, hook_id: str) -> None:
        """Record that a hook was just used.  Keeps only the 50 most recent."""
        self.r.zadd(RK.HOOKS_RECENT, {hook_id: time.time()})
        # Trim to last 50 entries
        self.r.zremrangebyrank(RK.HOOKS_RECENT, 0, -51)

    def get_recent_hook_ids(self, count: int = 30) -> List[str]:
        """Return up to `count` most recently used hook IDs (newest first)."""
        return self.r.zrevrange(RK.HOOKS_RECENT, 0, count - 1)

    # ═════════════════════════════════════════════════════════════════════════
    # SYSTEM HEALTH  (Dead Man's Switch)
    # ═════════════════════════════════════════════════════════════════════════

    def heartbeat(self) -> None:
        """
        Called by every GitHub Actions workflow on startup.
        The health key expires after 6 hours.  If it goes missing,
        the queue_health_check workflow sends an alert and pauses publishing.
        """
        self.r.setex(
            RK.SYSTEM_HEALTH,
            21_600,   # 6 hours
            json.dumps({"alive": True, "ts": time.time()}),
        )
        logger.debug("heartbeat_sent")

    def is_system_healthy(self) -> bool:
        """Return True if the system has sent a heartbeat in the last 6 hours."""
        return bool(self.r.exists(RK.SYSTEM_HEALTH))

    def record_last_publish(self, video_type: str) -> None:
        """Stamp the time of the last successful publish for a video type."""
        self.r.set(RK.last_publish(video_type), str(time.time()))

    def get_last_publish_time(self, video_type: str) -> Optional[float]:
        """Return the unix timestamp of the last successful publish, or None."""
        val = self.r.get(RK.last_publish(video_type))
        return float(val) if val else None

    def get_seconds_since_last_publish(self, video_type: str) -> Optional[float]:
        ts = self.get_last_publish_time(video_type)
        return (time.time() - ts) if ts is not None else None

    # ═════════════════════════════════════════════════════════════════════════
    # CACHE  (TTL-backed, invalidated by COS after rule changes)
    # ═════════════════════════════════════════════════════════════════════════

    def cache_growth_rules(self, rules: Dict, ttl_seconds: int = 3_600) -> None:
        self.r.setex(RK.GROWTH_RULES, ttl_seconds, json.dumps(rules))

    def get_cached_growth_rules(self) -> Optional[Dict]:
        raw = self.r.get(RK.GROWTH_RULES)
        return json.loads(raw) if raw else None

    def cache_channel_config(self, config: Dict, ttl_seconds: int = 3_600) -> None:
        self.r.setex(RK.CHANNEL_CONFIG, ttl_seconds, json.dumps(config))

    def get_cached_channel_config(self) -> Optional[Dict]:
        raw = self.r.get(RK.CHANNEL_CONFIG)
        return json.loads(raw) if raw else None

    def cache_war_room(self, snapshot: Dict, ttl_seconds: int = 300) -> None:
        self.r.setex(RK.WAR_ROOM, ttl_seconds, json.dumps(snapshot, default=str))

    def get_cached_war_room(self) -> Optional[Dict]:
        raw = self.r.get(RK.WAR_ROOM)
        return json.loads(raw) if raw else None

    def invalidate_all_caches(self) -> None:
        """Drop all cached data — call after any COS rule change."""
        self.r.delete(RK.GROWTH_RULES, RK.CHANNEL_CONFIG, RK.WAR_ROOM)
        logger.info("redis_caches_invalidated")

    # ═════════════════════════════════════════════════════════════════════════
    # GENERIC UTILITIES
    # ═════════════════════════════════════════════════════════════════════════

    def set_with_ttl(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Generic serialise-and-store with TTL."""
        self.r.setex(key, ttl_seconds, json.dumps(value, default=str))

    def get_json(self, key: str) -> Optional[Any]:
        """Generic get-and-deserialise."""
        raw = self.r.get(key)
        return json.loads(raw) if raw else None

    def delete(self, *keys: str) -> int:
        """Delete one or more keys.  Returns count deleted."""
        return self.r.delete(*keys)

    def ping(self) -> bool:
        """Return True if the Redis server responds to PING."""
        try:
            return self.r.ping()
        except Exception:
            return False

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _end_of_month_unix() -> int:
        """Unix timestamp for the final second of the current calendar month (UTC)."""
        import calendar
        now = datetime.utcnow()
        last_day = calendar.monthrange(now.year, now.month)[1]
        end = datetime(now.year, now.month, last_day, 23, 59, 59)
        return int(end.timestamp())


# ─────────────────────────────────────────────────────────────────────────────
# Module-level accessor
# ─────────────────────────────────────────────────────────────────────────────

_redis_instance: Optional[RedisClient] = None


def get_redis() -> RedisClient:
    """Return the process-level singleton RedisClient."""
    global _redis_instance
    if _redis_instance is None:
        _redis_instance = RedisClient()
    return _redis_instance
