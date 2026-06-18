"""
protection/duplicate_guard.py
"""
from __future__ import annotations
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional
import structlog
from storage.redis_client import get_redis
from storage.supabase_client import get_db

logger = structlog.get_logger(__name__)

_TITLE_SIMILARITY_THRESHOLD = 0.82
_TEXT_SIMILARITY_THRESHOLD  = 0.85
_RECENT_CHECK_COUNT = 40
_RECENT_TEXTS_KEY   = "yta:dedup:recent_full_texts"
_RECENT_TEXTS_MAX   = 40


@dataclass
class DuplicateCheckResult:
    is_duplicate: bool
    reason:       Optional[str] = None
    similar_to:   Optional[str] = None
    similarity:   float = 0.0


class DuplicateGuard:

    def __init__(self) -> None:
        self._redis = get_redis()
        self._db    = get_db()

    # ── Exact checks (Redis hash) ────────────────────────────────────────────

    def check_script(self, script_text: str) -> DuplicateCheckResult:
        if self._redis.is_script_duplicate(script_text):
            return DuplicateCheckResult(True, "exact_script_match_within_90_days")
        return DuplicateCheckResult(False)

    def check_title(self, title: str) -> DuplicateCheckResult:
        if self._redis.is_title_duplicate(title):
            return DuplicateCheckResult(True, "exact_title_match_within_60_days")

        try:
            recent = self._db.get_recent_published(limit=_RECENT_CHECK_COUNT)
            for r in recent:
                other = r.get("title") or ""
                if not other:
                    continue
                ratio = SequenceMatcher(None, title.lower(), other.lower()).ratio()
                if ratio >= _TITLE_SIMILARITY_THRESHOLD:
                    return DuplicateCheckResult(
                        True, "title_too_similar_to_recent", other, round(ratio, 3)
                    )
        except Exception as exc:
            logger.debug("duplicate_title_db_check_skip", error=str(exc)[:80])

        return DuplicateCheckResult(False)

    # ── Near-duplicate full-text check (Redis list of recent scripts) ────────

    def check_full_text(self, full_text: str) -> DuplicateCheckResult:
        try:
            recents = self._redis.r.lrange(_RECENT_TEXTS_KEY, 0, _RECENT_TEXTS_MAX - 1)
            for other in recents:
                ratio = SequenceMatcher(None, full_text.lower(), other.lower()).ratio()
                if ratio >= _TEXT_SIMILARITY_THRESHOLD:
                    return DuplicateCheckResult(
                        True, "script_too_similar_to_recent", None, round(ratio, 3)
                    )
        except Exception as exc:
            logger.debug("duplicate_text_check_skip", error=str(exc)[:80])
        return DuplicateCheckResult(False)

    # ── Combined check ────────────────────────────────────────────────────────

    def check_all(
        self, script_text: str, title: str, full_text: str
    ) -> DuplicateCheckResult:
        for check in (
            self.check_script(script_text),
            self.check_title(title),
            self.check_full_text(full_text),
        ):
            if check.is_duplicate:
                logger.warning(
                    "duplicate_detected",
                    reason=check.reason,
                    similarity=check.similarity,
                )
                return check
        return DuplicateCheckResult(False)

    # ── Registration (call after a video passes all gates) ──────────────────

    def register(self, script_text: str, title: str, full_text: str) -> None:
        self._redis.register_script(script_text, ttl_days=90)
        self._redis.register_title(title, ttl_days=60)
        try:
            pipe = self._redis.r.pipeline(transaction=True)
            pipe.lpush(_RECENT_TEXTS_KEY, full_text)
            pipe.ltrim(_RECENT_TEXTS_KEY, 0, _RECENT_TEXTS_MAX - 1)
            pipe.execute()
        except Exception as exc:
            logger.debug("register_full_text_skip", error=str(exc)[:80])


_instance: Optional[DuplicateGuard] = None

def get_duplicate_guard() -> DuplicateGuard:
    global _instance
    if _instance is None:
        _instance = DuplicateGuard()
    return _instance
