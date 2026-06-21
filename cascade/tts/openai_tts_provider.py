"""
cascade/tts/openai_tts_provider.py

TTS Provider: OpenAI  (Final Fallback — official, stable, small cost)

Positioned LAST in the cascade, after all 3 free ElevenLabs keys and free
edge-tts. This provider exists specifically so the system can never be
left with zero working TTS options in a single run.

Why this exists
────────────────
edge-tts is an unofficial, reverse-engineered client for Microsoft Edge's
internal "Read Aloud" API. It has repeatedly broken in production (stale
TrustedClientToken, then a newer Sec-MS-GEC anti-abuse signature that
also failed) despite using the latest available package version — this
is an ongoing, externally-controlled instability outside this project's
control. Relying on it as the *only* free-tier-priced fallback is not
production-stable.

OpenAI's /v1/audio/speech endpoint is official, documented, and has not
changed its authentication or request format. Using OPENAI_API_KEY (an
existing secret, already used for LLM cascade fallback — zero new
secrets required) here closes the gap completely.

Cost
────
Model "tts-1" is priced at $15 / 1,000,000 characters. A typical Short
script is ~700-900 characters, so even if this fallback were used for
EVERY video (which it shouldn't be — it only activates when all 4
cheaper options fail in the same run) the cost is roughly $0.01-0.015
per video, i.e. a few cents per day at 5 Shorts/day.

No alignment data
──────────────────
OpenAI's TTS endpoint does not return word/character timing data, so
alignment=None — identical to the edge-tts and ElevenLabs-plain-convert
fallback paths the subtitle engine already supports.

Required GitHub Secret
──────────────────────
  OPENAI_API_KEY   (already configured — shared with cascade/llm/openai_provider.py)
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

_MODEL = "tts-1"
_FEMALE_VOICE = "nova"
_MALE_VOICE = "onyx"
_MAX_INPUT_CHARS = 4096   # OpenAI TTS hard limit per request

_AUTH_PATTERNS = [r"\b401\b", r"\binvalid_api_key\b", r"\bauthentication\b", r"\bincorrect api key\b"]
_QUOTA_PATTERNS = [r"\binsufficient_quota\b", r"\bbilling\b", r"\b429\b", r"\bquota\b"]


def _matches_any(patterns, text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


class OpenAITTSProvider(BaseProvider):
    """
    OpenAI text-to-speech provider. Stable, official, small per-character
    cost. Always tried last in the TTS cascade.
    """

    provider_name = "openai_tts"
    is_free_tier = False
    cascade_category = "tts"

    def __init__(self) -> None:
        self._client: Optional[Any] = None

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return self.env_present("OPENAI_API_KEY")

    # ── Lazy client ───────────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        return self._client

    # ── Core execution ────────────────────────────────────────────────────────

    def execute(self, **kwargs: Any) -> ProviderResult:
        """
        kwargs expected
        ───────────────
        text          str  — narration text to synthesise
        voice_gender  str  — "female" or "male" (drives voice selection;
                             the ElevenLabs voice_id kwarg, if present, is
                             ignored — it is not a valid OpenAI voice name)
        """
        original_text: str = kwargs.get("text", "").strip()
        gender: str = kwargs.get("voice_gender", "female").lower()

        if not original_text:
            return ProviderResult.failure(
                self.provider_name, "Empty text received.", retriable=False
            )

        text = original_text
        if len(text) > _MAX_INPUT_CHARS:
            text = text[:_MAX_INPUT_CHARS]
            logger.warning(
                "openai_tts_text_truncated",
                original_len=len(original_text), truncated_to=_MAX_INPUT_CHARS,
            )

        voice = _FEMALE_VOICE if gender == "female" else _MALE_VOICE
        char_count = len(text)

        try:
            client = self._get_client()
            response = client.audio.speech.create(
                model=_MODEL, voice=voice, input=text, response_format="mp3",
            )
            audio_bytes = (
                response.content if hasattr(response, "content") else response.read()
            )
        except Exception as exc:
            err_lower = str(exc).lower()
            if _matches_any(_AUTH_PATTERNS, err_lower):
                logger.error(
                    "openai_tts_auth_error",
                    action_required="Check the OPENAI_API_KEY GitHub Secret value.",
                )
                return ProviderResult.failure(
                    self.provider_name, f"OpenAI TTS auth error: {exc}", retriable=False
                )
            if _matches_any(_QUOTA_PATTERNS, err_lower):
                logger.error(
                    "openai_tts_quota_or_billing_error",
                    action_required=(
                        "This OpenAI account has no available quota/credits "
                        "for audio generation. Add a payment method or "
                        "billing limit at https://platform.openai.com/settings/billing."
                    ),
                )
                return ProviderResult.failure(
                    self.provider_name, f"OpenAI TTS quota/billing error: {exc}", retriable=False
                )
            return ProviderResult.failure(self.provider_name, f"OpenAI TTS error: {exc}")

        if not audio_bytes:
            return ProviderResult.failure(
                self.provider_name, "OpenAI TTS returned empty audio."
            )

        logger.info(
            "openai_tts_success", voice=voice, char_count=char_count, model=_MODEL,
        )

        data: Dict[str, Any] = {
            "audio_bytes": audio_bytes,
            "alignment": None,
            "voice_id": voice,
            "char_count": char_count,
            "format": "mp3",
        }
        meta: Dict[str, Any] = {
            "provider": self.provider_name,
            "model": _MODEL,
            "voice": voice,
            "char_count": char_count,
            "has_alignment": False,
        }
        return ProviderResult(
            success=True, data=data, provider_used=self.provider_name, metadata=meta,
        )


_instance: Optional[OpenAITTSProvider] = None

def get_openai_tts_provider() -> OpenAITTSProvider:
    global _instance
    if _instance is None:
        _instance = OpenAITTSProvider()
    return _instance
