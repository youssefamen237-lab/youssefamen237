"""
cascade/tts/elevenlabs_voice_resolver.py

Solves the recurring "HTTP 402 — Free users cannot use library voices"
failure class at its root, rather than requiring a human to run a
diagnostic script and hand-edit GitHub Secrets every time it recurs
(e.g. after an account downgrade, a voice being removed from "My Voices",
or a new key being added with a different accessible voice set).

How it works
────────────
ElevenLabs' GET /v1/voices endpoint returns EXACTLY the set of voices a
given API key can use via the API right now — premade defaults, the
account's own cloned voices, and anything explicitly added to "My
Voices". Any voice_id NOT in that response will 402 for that key,
regardless of category labels.

For every (key, gender) pair, this resolver:
  1. Checks a 7-day Redis cache first (voice rosters change rarely).
  2. On a cache miss, calls GET /v1/voices for that specific key.
  3. If the user's statically-configured voice_id IS in that key's
     accessible set, keeps using it exactly as configured (respects
     intentional choices, zero behaviour change for correctly-configured
     setups).
  4. Otherwise, picks the best gender-matching accessible voice instead
     (preferring "premade" category), so the pipeline keeps working
     without any manual intervention.
  5. If the API call itself fails for any reason (network, invalid key),
     returns None — the caller falls back to the originally-configured
     voice_id unchanged, exactly as before this module existed. This
     resolver can only make voice selection MORE robust, never less.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import requests
import structlog

logger = structlog.get_logger(__name__)

_VOICES_URL = "https://api.elevenlabs.io/v1/voices"
_CACHE_TTL_SECONDS = 7 * 24 * 3600   # 7 days — voice rosters change rarely
_CACHE_KEY_PREFIX = "yta:elevenlabs:accessible_voices"
_REQUEST_TIMEOUT = 15

# Last-resort gender heuristic for the (rare) case where ElevenLabs returns
# a voice with no "labels.gender" metadata. Covers the long-standing
# classic premade roster; any voice not listed here simply isn't used for
# gender-based preference (falls through to "any accessible voice").
_KNOWN_FEMALE_NAMES = frozenset({
    "rachel", "bella", "domi", "elli", "dorothy", "charlotte", "matilda",
    "grace", "freya", "gigi", "nicole", "serena", "jessie", "glinda",
    "mimi", "emily",
})
_KNOWN_MALE_NAMES = frozenset({
    "adam", "antoni", "arnold", "callum", "charlie", "clyde", "daniel",
    "dave", "drew", "ethan", "fin", "george", "giovanni", "harry", "james",
    "jeremy", "joseph", "josh", "liam", "matthew", "michael", "patrick",
    "paul", "ryan", "sam", "thomas",
})


class ElevenLabsVoiceResolver:

    def __init__(self) -> None:
        self._memory_cache: Dict[str, Dict[str, Dict]] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def resolve_best_voice_id(
        self,
        key_env: str,
        api_key: str,
        gender: str,
        configured_voice_id: str,
    ) -> Optional[str]:
        """
        Return the best voice_id this key should use, or None if resolution
        was not possible (caller should fall back to configured_voice_id).
        """
        accessible = self._get_accessible_voices(key_env, api_key)
        if accessible is None:
            return None
        if not accessible:
            logger.warning(
                "elevenlabs_zero_accessible_voices",
                key_env=key_env,
                hint=(
                    "This key has zero voices accessible via the API. "
                    "Verify the API key is correct and the account has at "
                    "least the default premade voices."
                ),
            )
            return None

        if configured_voice_id and configured_voice_id in accessible:
            return configured_voice_id

        replacement = self._pick_best_match(accessible, gender)
        if replacement and replacement != configured_voice_id:
            logger.info(
                "elevenlabs_voice_auto_substituted",
                key_env=key_env,
                gender=gender,
                configured_voice_id=configured_voice_id or "(none)",
                substituted_voice_id=replacement,
                substituted_voice_name=accessible[replacement].get("name"),
                reason=(
                    "configured voice_id not accessible to this key "
                    "(likely a Voice Library voice requiring a paid plan)"
                ),
            )
        return replacement

    # ── Accessible voice lookup (Redis + in-process cached) ──────────────────

    def _get_accessible_voices(self, key_env: str, api_key: str) -> Optional[Dict[str, Dict]]:
        if key_env in self._memory_cache:
            return self._memory_cache[key_env]

        cached = self._read_redis_cache(key_env)
        if cached is not None:
            self._memory_cache[key_env] = cached
            return cached

        fetched = self._fetch_from_api(api_key)
        if fetched is None:
            return None   # API call failed — do not cache a failure

        self._memory_cache[key_env] = fetched
        self._write_redis_cache(key_env, fetched)
        return fetched

    def _fetch_from_api(self, api_key: str) -> Optional[Dict[str, Dict]]:
        try:
            resp = requests.get(
                _VOICES_URL, headers={"xi-api-key": api_key}, timeout=_REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            logger.debug("elevenlabs_voice_list_network_error", error=str(exc)[:100])
            return None

        if resp.status_code != 200:
            logger.debug(
                "elevenlabs_voice_list_fetch_failed",
                status=resp.status_code, body=resp.text[:150],
            )
            return None

        voices = resp.json().get("voices", [])
        return {
            v["voice_id"]: {
                "voice_id": v["voice_id"],
                "name": v.get("name", ""),
                "category": v.get("category", "unknown"),
                "labels": v.get("labels", {}) or {},
            }
            for v in voices
            if v.get("voice_id")
        }

    # ── Redis cache (best-effort — failures never block resolution) ─────────

    def _read_redis_cache(self, key_env: str) -> Optional[Dict[str, Dict]]:
        try:
            from storage.redis_client import get_redis
            cached = get_redis().get_json(f"{_CACHE_KEY_PREFIX}:{key_env}")
            return cached if isinstance(cached, dict) else None
        except Exception:
            return None

    def _write_redis_cache(self, key_env: str, voices: Dict[str, Dict]) -> None:
        try:
            from storage.redis_client import get_redis
            get_redis().set_with_ttl(
                f"{_CACHE_KEY_PREFIX}:{key_env}", voices, _CACHE_TTL_SECONDS
            )
        except Exception:
            pass

    def invalidate_cache(self, key_env: str) -> None:
        """Force a fresh API fetch on next resolution for this key."""
        self._memory_cache.pop(key_env, None)
        try:
            from storage.redis_client import get_redis
            get_redis().delete(f"{_CACHE_KEY_PREFIX}:{key_env}")
        except Exception:
            pass

    # ── Gender matching ───────────────────────────────────────────────────────

    def _pick_best_match(self, accessible: Dict[str, Dict], gender: str) -> Optional[str]:
        gender = (gender or "female").lower()

        scored: List[tuple] = []
        for vid, v in accessible.items():
            score = self._score_voice(v, gender)
            scored.append((score, vid))

        if not scored:
            return None

        scored.sort(key=lambda sv: sv[0], reverse=True)
        return scored[0][1]

    def _score_voice(self, voice: Dict, gender: str) -> int:
        """Higher is better. Gender match dominates; premade category is a tiebreaker."""
        score = 0
        label_gender = str((voice.get("labels") or {}).get("gender", "")).lower()
        name_lower = str(voice.get("name", "")).lower()

        if label_gender == gender:
            score += 100
        elif not label_gender:
            name_key = name_lower.split()[0] if name_lower else ""
            if gender == "female" and name_key in _KNOWN_FEMALE_NAMES:
                score += 80
            elif gender == "male" and name_key in _KNOWN_MALE_NAMES:
                score += 80
        elif label_gender and label_gender != gender:
            score -= 50   # wrong gender — strongly deprioritise but don't exclude

        if voice.get("category") == "premade":
            score += 10
        elif voice.get("category") in ("cloned", "generated"):
            score += 5

        return score


_instance: Optional[ElevenLabsVoiceResolver] = None

def get_voice_resolver() -> ElevenLabsVoiceResolver:
    global _instance
    if _instance is None:
        _instance = ElevenLabsVoiceResolver()
    return _instance
