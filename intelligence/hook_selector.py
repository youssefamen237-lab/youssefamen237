"""
intelligence/hook_selector.py
"""
from __future__ import annotations
import random, re
from dataclasses import dataclass
from typing import Dict, List, Optional
import structlog
from storage.supabase_client import get_db
from storage.redis_client import get_redis

logger = structlog.get_logger(__name__)

_VALID_HOOK_TYPES = frozenset({
    "danger", "size", "speed", "mystery", "intelligence",
    "survival", "comparison", "impossible", "weirdness",
    "record", "behavior", "discovery",
})

# Fallback hook_type per category when topic_dna is empty
_CATEGORY_DEFAULT_HOOK: Dict[str, str] = {
    "ocean": "danger", "animals": "danger", "space": "mystery",
    "nature": "mystery", "birds": "speed", "insects": "survival",
}

# Plain-text fallback used only if the hooks table has nothing usable
_GENERIC_FALLBACK_HOOKS: Dict[str, str] = {
    "danger":       "This is one of the most dangerous things in nature.",
    "size":         "This is far bigger than most people realize.",
    "mystery":      "Scientists still cannot fully explain this.",
    "intelligence": "This is smarter than most people think.",
    "speed":        "This moves faster than you'd ever expect.",
    "survival":     "This can survive in conditions that would kill almost anything else.",
    "comparison":   "Nothing else on Earth compares to this.",
    "impossible":   "This shouldn't be possible — but it happens.",
    "weirdness":    "Nature doesn't get much stranger than this.",
    "record":       "This holds one of nature's most extreme records.",
    "behavior":     "This behavior is unlike anything else in nature.",
    "discovery":    "This discovery changed how scientists understand nature.",
}

_PLACEHOLDER_PATTERN = re.compile(r"\[[A-Z0-9_/]+\]")


@dataclass
class HookSelection:
    hook_id:   Optional[str]
    hook_text: str
    hook_type: str


class HookSelector:

    def __init__(self) -> None:
        self._db    = get_db()
        self._redis = get_redis()

    # ── Public API ────────────────────────────────────────────────────────────

    def select_hook_type(self, topic_dna: Dict, category: str) -> str:
        """
        Pick the strongest emotional dimension from topic_dna and map it
        to a valid hook_type.  Falls back to a category default.
        """
        if topic_dna:
            scored = [
                (str(k).lower(), int(v))
                for k, v in topic_dna.items()
                if str(k).lower() in _VALID_HOOK_TYPES and isinstance(v, (int, float))
            ]
            if scored:
                scored.sort(key=lambda kv: kv[1], reverse=True)
                top_key, top_val = scored[0]
                if top_val >= 50:
                    return top_key

        return _CATEGORY_DEFAULT_HOOK.get(category, "danger")

    def select_hook(self, hook_type: str, topic_name: str) -> HookSelection:
        """
        Return a hook with [PLACEHOLDER] tokens filled in with topic_name.
        Rotation-aware: excludes hooks used in the last 30 calls.
        """
        if hook_type not in _VALID_HOOK_TYPES:
            hook_type = "discovery"

        recent_ids = self._safe_recent_hook_ids()

        rows = self._safe_get_hooks(hook_type, recent_ids)
        if not rows:
            # Retry without the recency exclusion
            rows = self._safe_get_hooks(hook_type, [])
        if not rows:
            # Try a different hook_type entirely
            for fallback_type in _VALID_HOOK_TYPES:
                rows = self._safe_get_hooks(fallback_type, [])
                if rows:
                    hook_type = fallback_type
                    break

        if rows:
            row = random.choice(rows)
            text = self._fill_placeholders(row["hook_text"], topic_name)
            return HookSelection(hook_id=row["hook_id"], hook_text=text, hook_type=hook_type)

        # Absolute fallback — never block the pipeline
        text = _GENERIC_FALLBACK_HOOKS.get(hook_type, _GENERIC_FALLBACK_HOOKS["discovery"])
        return HookSelection(hook_id=None, hook_text=text, hook_type=hook_type)

    def register_usage(self, hook_selection: HookSelection) -> None:
        """Mark a hook as used — updates Redis recency and DB usage_count."""
        if hook_selection.hook_id is None:
            return
        try:
            self._redis.mark_hook_used(hook_selection.hook_id)
        except Exception:
            pass
        try:
            self._db.increment_hook_usage(hook_selection.hook_id)
        except Exception:
            pass

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _safe_recent_hook_ids(self) -> List[str]:
        try:
            return self._redis.get_recent_hook_ids(count=30)
        except Exception:
            return []

    def _safe_get_hooks(self, hook_type: str, exclude_ids: List[str]) -> List[Dict]:
        try:
            return self._db.get_hooks_by_type(hook_type, exclude_ids=exclude_ids, limit=10)
        except Exception as exc:
            logger.debug("hook_fetch_failed", hook_type=hook_type, error=str(exc)[:80])
            return []

    @staticmethod
    def _fill_placeholders(text: str, topic_name: str) -> str:
        """Replace every [PLACEHOLDER] token with topic_name."""
        return _PLACEHOLDER_PATTERN.sub(topic_name, text)


_instance: Optional[HookSelector] = None

def get_hook_selector() -> HookSelector:
    global _instance
    if _instance is None:
        _instance = HookSelector()
    return _instance
