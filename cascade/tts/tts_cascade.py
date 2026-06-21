"""
cascade/tts/tts_cascade.py

TTS Cascade Coordinator — the single import point for all voice generation.

Responsibilities
────────────────
  1. Voice selection     Resolve the correct ElevenLabs voice_id based on the
                         requested gender, the Redis rotation state, and the
                         consecutive-use limits defined in growth_rules.
  2. Key ordering        Dynamically order the three ElevenLabs providers by
                         remaining quota (most quota first) so the key with the
                         most headroom is always tried first.
  3. Cascade routing     Build and execute the CascadeManager with all five
                         providers: ElevenLabs Key 1 → Key 2 → Key 3 →
                         edge-tts (free) → OpenAI TTS (small-cost, stable
                         final fallback — see openai_tts_provider.py for
                         why this final tier exists).
  4. Post-success hooks  Update Redis voice rotation state and record the
                         last-publish timestamp after a successful synthesis.

Public interface
────────────────
  generate_audio(text, gender, voice_id_override) → TTSResult
  get_tts()                                        → TTSCascade singleton

TTSResult is a named-tuple-like dataclass:
  audio_bytes : bytes       Raw MP3 audio
  alignment   : dict|None   Character/word-level timing for subtitle sync
  voice_id    : str         Voice ID actually used
  voice_gender: str         "female" or "male"
  char_count  : int         Characters consumed (for quota awareness)
  provider    : str         Which provider delivered the audio
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import structlog

from cascade.base_provider import ProviderResult
from cascade.cascade_manager import CascadeManager, CircuitBreaker
from cascade.tts.edge_tts_provider import EdgeTTSProvider
from cascade.tts.elevenlabs_key1_provider import ElevenLabsKey1Provider
from cascade.tts.elevenlabs_key2_provider import ElevenLabsKey2Provider
from cascade.tts.elevenlabs_key3_provider import ElevenLabsKey3Provider
from cascade.tts.openai_tts_provider import OpenAITTSProvider

logger = structlog.get_logger(__name__)

# Shared circuit breaker so failures carry across multiple calls in the same run
_SHARED_BREAKER = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=300)

# ── Voice ID secret names ─────────────────────────────────────────────────────
_FEMALE_VOICE_ENVS: List[str] = [
    "ELEVENLABS_VOICE_ID_FEMALE",
    "ELEVENLABS_VOICE_ID_FEMALE_2_CASSIDY",
    "ELEVENLABS_VOICE_ID_FEMALE_3_ALLISON",
]
_MALE_VOICE_ENVS: List[str] = [
    "ELEVENLABS_VOICE_ID_MALE",
    "ELEVENLABS_VOICE_ID_MALE_2_MARK",
    "ELEVENLABS_VOICE_ID_MALE_3_YOUNG_JAMAL",
]

# Edge-TTS neural voice names used when all ElevenLabs keys are exhausted
_EDGE_FEMALE_VOICES: List[str] = [
    "en-US-AriaNeural",
    "en-US-JennyNeural",
    "en-GB-SoniaNeural",
]
_EDGE_MALE_VOICES: List[str] = [
    "en-US-GuyNeural",
    "en-US-ChristopherNeural",
    "en-GB-RyanNeural",
]


# ─────────────────────────────────────────────────────────────────────────────
# Return type
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TTSResult:
    """Normalised result returned by TTSCascade.generate_audio()."""
    audio_bytes: bytes
    alignment: Optional[Dict]     # Character/word-level timing (may be None)
    voice_id: str                 # Voice ID or edge-tts voice name used
    voice_gender: str             # "female" or "male"
    char_count: int
    provider: str                 # e.g. "elevenlabs_key1" or "edge_tts"
    has_alignment: bool = False

    def __post_init__(self) -> None:
        self.has_alignment = self.alignment is not None


# ─────────────────────────────────────────────────────────────────────────────
# TTSCascade
# ─────────────────────────────────────────────────────────────────────────────

class TTSCascade:
    """
    Singleton TTS facade.  Wires all four providers, handles voice selection,
    and exposes a single generate_audio() method used by the voice_generator engine.
    """

    def __init__(self) -> None:
        self._key1 = ElevenLabsKey1Provider()
        self._key2 = ElevenLabsKey2Provider()
        self._key3 = ElevenLabsKey3Provider()
        self._edge = EdgeTTSProvider()
        self._openai = OpenAITTSProvider()

    # ═════════════════════════════════════════════════════════════════════════
    # Public API
    # ═════════════════════════════════════════════════════════════════════════

    def generate_audio(
        self,
        text: str,
        gender: str = "female",
        voice_id_override: Optional[str] = None,
    ) -> TTSResult:
        """
        Synthesise speech for the given text.

        Parameters
        ──────────
        text              The narration script to synthesise.
        gender            "female" or "male" — drives voice selection and
                          edge-tts fallback voice choice.
        voice_id_override If set, bypasses rotation logic and uses this
                          specific ElevenLabs voice ID directly.

        Returns TTSResult on success.
        Raises RuntimeError only when ALL four providers fail (including edge-tts,
        which has no quota — this should be essentially impossible in production).
        """
        text = text.strip()
        if not text:
            raise ValueError("generate_audio() received empty text.")

        gender = gender.lower()
        if gender not in ("female", "male"):
            gender = "female"

        # Resolve the ElevenLabs voice_id to pass to providers
        el_voice_id = voice_id_override or self._select_elevenlabs_voice(gender)
        # Resolve the edge-tts voice name (used only by EdgeTTSProvider)
        edge_voice = self._select_edge_voice(gender)

        # Build provider list ordered by remaining quota
        providers = self._build_ordered_providers(el_voice_id)

        manager = CascadeManager(
            providers=providers,
            category="tts",
            max_retries_per_provider=2,
            circuit_breaker=_SHARED_BREAKER,
        )

        result: ProviderResult = manager.execute(
            text=text,
            voice_id=el_voice_id if "edge" not in "placeholder" else edge_voice,
            model_id="eleven_multilingual_v2",
            voice_gender=gender,     # used by edge_tts for fallback voice selection
        )

        if not result.success:
            raise RuntimeError(
                f"TTS cascade exhausted for all providers. "
                f"Error: {result.error}"
            )

        # ── Post-success: update rotation state ───────────────────────────────
        used_provider = result.provider_used
        actual_voice_id = result.data.get("voice_id", el_voice_id)
        self._update_rotation_state(gender=gender, voice_id=actual_voice_id)

        logger.info(
            "tts_cascade_success",
            provider=used_provider,
            gender=gender,
            voice_id=actual_voice_id[:10] + "…" if len(actual_voice_id) > 10 else actual_voice_id,
            char_count=result.data.get("char_count", len(text)),
            has_alignment=result.data.get("alignment") is not None,
        )

        return TTSResult(
            audio_bytes=result.data["audio_bytes"],
            alignment=result.data.get("alignment"),
            voice_id=actual_voice_id,
            voice_gender=gender,
            char_count=result.data.get("char_count", len(text)),
            provider=used_provider,
        )

    # ═════════════════════════════════════════════════════════════════════════
    # Voice selection
    # ═════════════════════════════════════════════════════════════════════════

    def _select_elevenlabs_voice(self, gender: str) -> str:
        """
        Select the ElevenLabs voice_id for the requested gender, respecting
        the consecutive-use limits stored in Redis.

        Logic:
          - Load all available voice IDs for the gender from environment.
          - Read Redis rotation state.
          - If the current voice has been used consecutively >= limit, rotate.
          - Otherwise return the primary voice.
        """
        voice_ids = self._get_elevenlabs_voice_ids(gender)
        if not voice_ids:
            logger.warning(
                "no_elevenlabs_voice_ids_configured",
                gender=gender,
                hint="Set ELEVENLABS_VOICE_ID_FEMALE / ELEVENLABS_VOICE_ID_MALE in secrets.",
            )
            return ""

        # Check rotation limits (non-blocking — if Redis fails use primary voice)
        try:
            from storage.redis_client import get_redis
            state = get_redis().get_voice_state()
            last_id = state.get("last_voice_id", "")
            consecutive_voice_uses = state.get("voice_id_consecutive", 0)

            # Load configured limit (default: rotate after 3 consecutive uses)
            try:
                from storage.supabase_client import get_db
                rule = get_db().get_rule("voice_consecutive_limit")
                max_consecutive = int(
                    (rule or {}).get("max_same_voice_id_consecutive", 3)
                )
            except Exception:
                max_consecutive = 3

            if consecutive_voice_uses >= max_consecutive and len(voice_ids) > 1:
                # Rotate to the next available voice
                try:
                    idx = voice_ids.index(last_id)
                    return voice_ids[(idx + 1) % len(voice_ids)]
                except ValueError:
                    return voice_ids[0]

            # Keep using the same voice if it matches gender
            if last_id in voice_ids:
                return last_id

        except Exception:
            pass  # Redis unavailable — use primary voice

        return voice_ids[0]

    @staticmethod
    def _get_elevenlabs_voice_ids(gender: str) -> List[str]:
        """Return all configured voice IDs for the given gender (non-empty only)."""
        env_names = _FEMALE_VOICE_ENVS if gender == "female" else _MALE_VOICE_ENVS
        ids = [os.getenv(env, "").strip() for env in env_names]
        return [v for v in ids if v]

    @staticmethod
    def _select_edge_voice(gender: str) -> str:
        """Return the primary edge-tts voice for the given gender."""
        return _EDGE_FEMALE_VOICES[0] if gender == "female" else _EDGE_MALE_VOICES[0]

    # ═════════════════════════════════════════════════════════════════════════
    # Provider ordering
    # ═════════════════════════════════════════════════════════════════════════

    def _build_ordered_providers(self, el_voice_id: str) -> list:
        """
        Order the three ElevenLabs providers by remaining monthly quota
        (highest remaining first), then append edge-tts as the always-last fallback.

        This ensures we never artificially exhaust a key that still has headroom
        while another key is at capacity.
        """
        try:
            from storage.redis_client import get_redis
            redis = get_redis()
            key_remaining = {
                1: 100_000 - redis.get_tts_chars_used(1),
                2: 100_000 - redis.get_tts_chars_used(2),
                3: 100_000 - redis.get_tts_chars_used(3),
            }
            provider_map = {
                1: self._key1,
                2: self._key2,
                3: self._key3,
            }
            sorted_keys = sorted(key_remaining, key=lambda k: key_remaining[k], reverse=True)
            ordered_el = [provider_map[k] for k in sorted_keys]
        except Exception:
            # Redis unavailable — use default order
            ordered_el = [self._key1, self._key2, self._key3]

        # EdgeTTSProvider needs the edge voice, not an ElevenLabs ID.
        # The provider resolves the edge voice internally from voice_gender kwarg.
        # OpenAITTSProvider similarly resolves its own voice from voice_gender
        # and ignores the ElevenLabs voice_id kwarg entirely. It is always
        # last: free options (3 ElevenLabs keys, then edge-tts) are
        # exhausted first; this small-cost-but-stable tier only activates
        # when every free option has failed in the same run.
        return ordered_el + [self._edge, self._openai]

    # ═════════════════════════════════════════════════════════════════════════
    # Post-success hooks
    # ═════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _update_rotation_state(gender: str, voice_id: str) -> None:
        """Update Redis voice rotation state after a successful synthesis."""
        try:
            from storage.redis_client import get_redis
            get_redis().update_voice_state(gender=gender, voice_id=voice_id)
        except Exception:
            pass  # Non-critical — pipeline continues regardless

    # ═════════════════════════════════════════════════════════════════════════
    # Diagnostics
    # ═════════════════════════════════════════════════════════════════════════

    def get_status(self) -> Dict:
        """Return TTS cascade health for the war room dashboard."""
        try:
            from storage.redis_client import get_redis
            redis = get_redis()
            quota = {
                f"key{i}_chars_used": redis.get_tts_chars_used(i)
                for i in [1, 2, 3]
            }
            voice_state = redis.get_voice_state()
        except Exception:
            quota = {}
            voice_state = {}

        female_ids = self._get_elevenlabs_voice_ids("female")
        male_ids = self._get_elevenlabs_voice_ids("male")

        return {
            "category": "tts",
            "elevenlabs_keys_configured": sum(
                1 for k in ["ELEVEN_API_KEY", "ELEVEN_API_KEY_2", "ELEVEN_API_KEY_3"]
                if os.getenv(k, "").strip()
            ),
            "female_voices_configured": len(female_ids),
            "male_voices_configured": len(male_ids),
            "edge_tts_available": self._edge.is_available(),
            "openai_tts_available": self._openai.is_available(),
            "quota": quota,
            "voice_rotation": voice_state,
            "circuit_status": _SHARED_BREAKER.get_status(),
        }

    def get_voice_ids_for_gender(self, gender: str) -> List[str]:
        """Expose voice ID list for testing and diagnostics."""
        return self._get_elevenlabs_voice_ids(gender)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton accessor
# ─────────────────────────────────────────────────────────────────────────────

_tts_instance: Optional[TTSCascade] = None


def get_tts() -> TTSCascade:
    """
    Return the process-level singleton TTSCascade.
    All engines call this — never instantiate TTSCascade directly.
    """
    global _tts_instance
    if _tts_instance is None:
        _tts_instance = TTSCascade()
    return _tts_instance
