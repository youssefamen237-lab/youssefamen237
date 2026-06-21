"""
cascade/tts/elevenlabs_key1_provider.py

ElevenLabs TTS — Primary API Key (ELEVEN_API_KEY)

Contains two classes:
  ElevenLabsBaseProvider   — All shared ElevenLabs logic (inherited by Key 2 & 3)
  ElevenLabsKey1Provider   — Thin subclass bound to ELEVEN_API_KEY / key_index=1

Key feature: uses convert_with_timestamps() so every response includes
character-level timing data. The subtitle engine uses this to render
perfectly synchronised word-by-word captions without any ASR model.

ProviderResult.data structure
──────────────────────────────
{
  "audio_bytes":  bytes,       Raw MP3 audio
  "alignment": {
    "type":       "character",
    "characters": [...],       List[str]
    "start_times":[...],       List[float] in seconds
    "end_times":  [...],       List[float] in seconds
  },
  "voice_id":    str,
  "char_count":  int,          Used for quota tracking
  "format":      "mp3_44100_128",
}

Error classification
──────────────────────
ElevenLabs failures fall into two very different buckets, and conflating
them wastes real time in a 5-shorts/day production loop:

  PERMANENT (retriable=False, key blocked for the rest of this run)
    • HTTP 402 "payment_required" / "paid_plan_required" — the configured
      voice_id is a Voice Library (shared/community) voice, which ElevenLabs
      restricts to paid-plan API access. This is an ACCOUNT-LEVEL
      restriction: retrying — even with a different key — will fail
      identically for every Library voice on every free-tier account.
      See scripts/list_elevenlabs_voices.py to identify which configured
      voice_id secrets are Library voices vs. account-accessible
      (premade/cloned) voices.
    • HTTP 401 "invalid_api_key" — the key itself is wrong/revoked.

  TRANSIENT (retriable=True, default — normal backoff retry applies)
    • HTTP 429 rate-limit, 5xx server errors, network timeouts.

Required GitHub Secrets (Key 1 only)
──────────────────────────────────────
  ELEVEN_API_KEY
  ELEVENLABS_VOICE_ID_FEMALE            (primary female)
  ELEVENLABS_VOICE_ID_FEMALE_2_CASSIDY  (secondary female)
  ELEVENLABS_VOICE_ID_FEMALE_3_ALLISON  (tertiary female)
  ELEVENLABS_VOICE_ID_MALE              (primary male)
  ELEVENLABS_VOICE_ID_MALE_2_MARK       (secondary male)
  ELEVENLABS_VOICE_ID_MALE_3_YOUNG_JAMAL(tertiary male)
"""

from __future__ import annotations

import base64
import os
import re
from typing import Any, Dict, Optional

import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

# Soft monthly character limit per ElevenLabs Creator plan key.
# The cascade will prefer a key with remaining quota, but the hard
# enforcement is the API itself — we just avoid wasting requests.
_MONTHLY_CHAR_LIMIT = 100_000

_TTS_MODEL = "eleven_multilingual_v2"
_OUTPUT_FORMAT = "mp3_44100_128"

# ── Error classification patterns (word-boundary regex, not bare substring
#    containment — a bare `"rate" in text` check is a known false-positive
#    trap, see cascade/llm/gemini_provider.py for the exact bug this avoids) ──

_PAYMENT_REQUIRED_PATTERNS = [
    r"\b402\b", r"\bpayment_required\b", r"\bpaid_plan_required\b",
    r"\bfree users cannot use library voices\b", r"\bupgrade your subscription\b",
]
_AUTH_PATTERNS = [
    r"\b401\b", r"\binvalid_api_key\b", r"\bunauthorized\b",
]
_QUOTA_PATTERNS = [
    r"\bquota\b", r"\b429\b", r"\brate[ _-]?limit\b", r"\bbilling\b",
    r"\btoo many requests\b",
]


def _matches_any(patterns, text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


# ─────────────────────────────────────────────────────────────────────────────
# Shared ElevenLabs logic — subclassed by Key 1, 2 and 3
# ─────────────────────────────────────────────────────────────────────────────

class ElevenLabsBaseProvider(BaseProvider):
    """
    All shared ElevenLabs SDK logic lives here.
    Subclasses only need to set _key_env and _key_index.
    """

    cascade_category = "tts"
    is_free_tier = False

    # Overridden by each subclass
    _key_env: str = "ELEVEN_API_KEY"
    _key_index: int = 1

    def __init__(self) -> None:
        self._client: Optional[Any] = None
        self._permanently_blocked: bool = False

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        if not self.env_present(self._key_env):
            return False

        # Once this key has hit a deterministic, account-level failure
        # (402 payment-required, 401 invalid key) in this process, every
        # subsequent call with the same voice_id will fail identically.
        # Skip it immediately rather than re-attempting and re-failing on
        # every video for the rest of the run.
        if self._permanently_blocked:
            return False

        # Soft quota check via Redis (non-blocking — if Redis fails we proceed)
        try:
            from storage.redis_client import get_redis
            chars_used = get_redis().get_tts_chars_used(self._key_index)
            if chars_used >= _MONTHLY_CHAR_LIMIT:
                logger.info(
                    "elevenlabs_key_quota_exhausted",
                    key_index=self._key_index,
                    chars_used=chars_used,
                    limit=_MONTHLY_CHAR_LIMIT,
                )
                return False
        except Exception:
            pass  # Redis unavailable — proceed optimistically
        return True

    # ── Lazy client ───────────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is None:
            from elevenlabs import ElevenLabs
            self._client = ElevenLabs(api_key=os.environ[self._key_env])
        return self._client

    # ── Core execution ────────────────────────────────────────────────────────

    def execute(self, **kwargs: Any) -> ProviderResult:
        """
        kwargs expected
        ───────────────
        text          str  — narration text to synthesise
        voice_id      str  — preferred ElevenLabs voice ID (rotation choice).
                             Treated as a PREFERENCE, not a hard requirement:
                             if this specific key cannot access it (e.g. it's
                             a Voice Library voice and this account is free
                             tier), it is transparently replaced with the
                             best gender-matching voice this key CAN access.
                             See elevenlabs_voice_resolver.py.
        voice_gender  str  — "female" or "male", used both for edge-tts
                             fallback selection and for resolver gender
                             matching when a substitution is needed.
        model_id      str  — default "eleven_multilingual_v2"
        """
        text: str = kwargs.get("text", "").strip()
        preferred_voice_id: str = kwargs.get("voice_id", "")
        gender: str = kwargs.get("voice_gender", "female").lower()
        model_id: str = kwargs.get("model_id", _TTS_MODEL)

        if not text:
            return ProviderResult.failure(
                self.provider_name, "Empty text received.", retriable=False
            )
        if not preferred_voice_id:
            return ProviderResult.failure(
                self.provider_name, "No voice_id provided.", retriable=False
            )

        voice_id = self._resolve_accessible_voice_id(preferred_voice_id, gender)
        if not voice_id:
            return ProviderResult.failure(
                self.provider_name,
                f"No accessible voice_id available for key {self._key_index} "
                f"(configured voice_id '{preferred_voice_id}' is not accessible "
                f"to this key and no substitute could be resolved).",
                retriable=False,
            )

        char_count = len(text)

        try:
            return self._call_with_timestamps(
                text=text,
                voice_id=voice_id,
                model_id=model_id,
                char_count=char_count,
            )
        except Exception as exc:
            return self._classify_and_fail(exc, voice_id)

    def _resolve_accessible_voice_id(self, preferred_voice_id: str, gender: str) -> str:
        """
        Returns the voice_id this key should actually use. Falls back to
        preferred_voice_id unchanged if dynamic resolution is unavailable
        for any reason (Redis down, network error, etc.) — this method can
        only improve voice selection, never make it worse than before this
        resolver existed.
        """
        try:
            from cascade.tts.elevenlabs_voice_resolver import get_voice_resolver
            api_key = os.environ.get(self._key_env, "")
            resolved = get_voice_resolver().resolve_best_voice_id(
                key_env=self._key_env,
                api_key=api_key,
                gender=gender,
                configured_voice_id=preferred_voice_id,
            )
            return resolved or preferred_voice_id
        except Exception as exc:
            logger.debug(
                "elevenlabs_voice_resolution_skipped",
                key_index=self._key_index, error=str(exc)[:100],
            )
            return preferred_voice_id

    def _classify_and_fail(self, exc: Exception, voice_id: str) -> ProviderResult:
        """
        Inspect the exception and return an appropriately-classified
        ProviderResult. PERMANENT failures (402/401) block this key for the
        rest of the run and skip the remaining retry attempts; TRANSIENT
        failures (429/5xx/network) retry normally.
        """
        err_str = str(exc)
        err_lower = err_str.lower()

        if _matches_any(_PAYMENT_REQUIRED_PATTERNS, err_lower):
            self._permanently_blocked = True
            self._mark_key_unavailable()
            logger.error(
                "elevenlabs_voice_requires_paid_plan",
                key_index=self._key_index,
                voice_id=voice_id,
                action_required=(
                    "This voice_id is from the ElevenLabs Voice Library "
                    "(shared/community voice), which requires a paid plan to "
                    "access via the API. Free-tier accounts can only use "
                    "premade default voices or voices you've cloned yourself. "
                    "Run scripts/list_elevenlabs_voices.py with this account's "
                    "API key to list which configured voice_id secrets are "
                    "actually accessible, then update the corresponding "
                    "ELEVENLABS_VOICE_ID_* GitHub Secret."
                ),
            )
            return ProviderResult.failure(
                self.provider_name,
                f"ElevenLabs API error (key {self._key_index}): {err_str}",
                retriable=False,
            )

        if _matches_any(_AUTH_PATTERNS, err_lower):
            self._permanently_blocked = True
            logger.error(
                "elevenlabs_key_invalid",
                key_index=self._key_index,
                action_required=f"Check the {self._key_env} GitHub Secret value.",
            )
            return ProviderResult.failure(
                self.provider_name,
                f"ElevenLabs API error (key {self._key_index}): {err_str}",
                retriable=False,
            )

        if _matches_any(_QUOTA_PATTERNS, err_lower):
            self._mark_key_unavailable()
            return ProviderResult.failure(
                self.provider_name,
                f"ElevenLabs API error (key {self._key_index}): {err_str}",
                retriable=False,   # quota won't refill within this run either
            )

        # Genuinely transient (network blip, 5xx, unexpected SDK error)
        return ProviderResult.failure(
            self.provider_name, f"ElevenLabs API error (key {self._key_index}): {err_str}"
        )

    def _call_with_timestamps(
        self,
        text: str,
        voice_id: str,
        model_id: str,
        char_count: int,
    ) -> ProviderResult:
        """
        Call convert_with_timestamps() to get audio + character-level alignment.
        Falls back to plain convert() if the timestamps endpoint fails for a
        reason OTHER than payment/auth (those are deterministic and would
        fail identically on the plain endpoint too — no point trying twice).
        """
        client = self._get_client()

        # ── Attempt 1: timestamps endpoint ────────────────────────────────────
        try:
            response = client.text_to_speech.convert_with_timestamps(
                voice_id=voice_id,
                text=text,
                model_id=model_id,
                output_format=_OUTPUT_FORMAT,
            )

            # Decode audio
            if hasattr(response, "audio_base64") and response.audio_base64:
                audio_bytes = base64.b64decode(response.audio_base64)
            else:
                raise ValueError("No audio_base64 in timestamp response.")

            # Extract alignment
            alignment_data = self._extract_alignment(response)

            return self._build_result(
                audio_bytes=audio_bytes,
                alignment=alignment_data,
                voice_id=voice_id,
                char_count=char_count,
            )

        except Exception as ts_exc:
            ts_err_lower = str(ts_exc).lower()
            if _matches_any(_PAYMENT_REQUIRED_PATTERNS, ts_err_lower) or \
               _matches_any(_AUTH_PATTERNS, ts_err_lower):
                # Deterministic account-level failure — re-raise immediately,
                # the plain convert() endpoint below would fail identically.
                raise

            logger.warning(
                "elevenlabs_timestamps_failed_fallback_to_plain",
                key_index=self._key_index,
                error=str(ts_exc),
            )

        # ── Attempt 2: plain convert (no alignment data) ──────────────────────
        audio_generator = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=model_id,
            output_format=_OUTPUT_FORMAT,
        )
        audio_bytes = b"".join(audio_generator)

        if not audio_bytes:
            return ProviderResult.failure(
                self.provider_name,
                f"ElevenLabs (key {self._key_index}) returned empty audio.",
            )

        return self._build_result(
            audio_bytes=audio_bytes,
            alignment=None,
            voice_id=voice_id,
            char_count=char_count,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_alignment(self, response: Any) -> Optional[Dict]:
        """
        Parse the alignment object from a convert_with_timestamps response.
        Returns a normalised dict or None if alignment data is absent.
        """
        try:
            aln = response.alignment
            if aln is None:
                return None
            chars = list(aln.characters)
            starts = list(aln.character_start_times_seconds)
            ends = list(aln.character_end_times_seconds)
            if not chars:
                return None
            return {
                "type": "character",
                "characters": chars,
                "start_times": [float(t) for t in starts],
                "end_times": [float(t) for t in ends],
            }
        except Exception as exc:
            logger.warning("elevenlabs_alignment_parse_error", error=str(exc))
            return None

    def _build_result(
        self,
        audio_bytes: bytes,
        alignment: Optional[Dict],
        voice_id: str,
        char_count: int,
    ) -> ProviderResult:
        """Build a successful ProviderResult and record quota usage."""
        # Record quota usage in Redis (non-blocking)
        try:
            from storage.redis_client import get_redis
            get_redis().add_tts_chars_used(self._key_index, char_count)
        except Exception:
            pass

        data: Dict[str, Any] = {
            "audio_bytes": audio_bytes,
            "alignment": alignment,
            "voice_id": voice_id,
            "char_count": char_count,
            "format": _OUTPUT_FORMAT,
        }
        meta: Dict[str, Any] = {
            "provider": self.provider_name,
            "key_index": self._key_index,
            "model": _TTS_MODEL,
            "voice_id": voice_id,
            "char_count": char_count,
            "has_alignment": alignment is not None,
        }
        logger.info(
            "elevenlabs_tts_success",
            key_index=self._key_index,
            voice_id=voice_id[:8] + "…",
            char_count=char_count,
            has_alignment=alignment is not None,
        )
        return ProviderResult(
            success=True,
            data=data,
            provider_used=self.provider_name,
            metadata=meta,
        )

    def _mark_key_unavailable(self) -> None:
        """Force-fill the Redis quota counter so is_available() returns False
        for this key on every subsequent call across the rest of this run
        (and any other process sharing the same Redis instance)."""
        try:
            from storage.redis_client import get_redis
            get_redis().add_tts_chars_used(self._key_index, _MONTHLY_CHAR_LIMIT)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Key 1 — Primary key
# ─────────────────────────────────────────────────────────────────────────────

class ElevenLabsKey1Provider(ElevenLabsBaseProvider):
    """ElevenLabs TTS using the primary API key (ELEVEN_API_KEY)."""
    provider_name = "elevenlabs_key1"
    _key_env = "ELEVEN_API_KEY"
    _key_index = 1
