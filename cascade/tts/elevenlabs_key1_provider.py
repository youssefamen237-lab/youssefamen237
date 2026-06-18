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

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        if not self.env_present(self._key_env):
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
        text        str  — narration text to synthesise
        voice_id    str  — ElevenLabs voice ID (already resolved by coordinator)
        model_id    str  — default "eleven_multilingual_v2"
        """
        text: str = kwargs.get("text", "").strip()
        voice_id: str = kwargs.get("voice_id", "")
        model_id: str = kwargs.get("model_id", _TTS_MODEL)

        if not text:
            return ProviderResult.failure(self.provider_name, "Empty text received.")
        if not voice_id:
            return ProviderResult.failure(self.provider_name, "No voice_id provided.")

        char_count = len(text)

        try:
            return self._call_with_timestamps(
                text=text,
                voice_id=voice_id,
                model_id=model_id,
                char_count=char_count,
            )
        except Exception as exc:
            err_str = str(exc)
            # Quota exceeded — mark key as exhausted in Redis
            if any(kw in err_str.lower() for kw in ("quota", "429", "rate", "billing")):
                self._mark_quota_exhausted()
            return ProviderResult.failure(
                self.provider_name, f"ElevenLabs API error (key {self._key_index}): {exc}"
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
        Falls back to plain convert() if the timestamps endpoint fails.
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

    def _mark_quota_exhausted(self) -> None:
        """Force-fill the Redis quota counter so is_available() returns False."""
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
