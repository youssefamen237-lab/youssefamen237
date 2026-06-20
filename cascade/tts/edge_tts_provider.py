"""
cascade/tts/edge_tts_provider.py

TTS Provider: Microsoft Edge-TTS  (Free Fallback — no API key required)

edge-tts streams audio and word-boundary events from Microsoft's neural
TTS service.  It requires no API key, has no character quota, and
produces high-quality English audio with natural prosody.

This provider is the last line of defence: it activates only when all
three ElevenLabs keys are exhausted or unavailable, ensuring the system
never halts video production due to TTS failures.

Voice selection
───────────────
  Female (primary)   en-US-AriaNeural         — warm, authoritative
  Female (secondary) en-US-JennyNeural        — friendly, clear
  Female (tertiary)  en-GB-SoniaNeural        — British accent variety
  Male   (primary)   en-US-GuyNeural          — confident, documentary
  Male   (secondary) en-US-ChristopherNeural  — deeper, calm
  Male   (tertiary)  en-GB-RyanNeural         — British accent variety

Alignment format
────────────────
  edge-tts provides WordBoundary events which we convert into the same
  alignment schema used by the ElevenLabs providers so the subtitle
  engine sees a uniform data structure regardless of which TTS was used.

Stability note
────────────────
  edge-tts is an UNOFFICIAL reverse-engineered client for the same
  backend that powers "Read Aloud" in Microsoft Edge. Microsoft rotates
  the WSS "TrustedClientToken" handshake periodically, which breaks
  older pinned versions of the edge-tts PyPI package with an HTTP 403
  ("Invalid response status") until the package is updated to a release
  that uses the current token. requirements.txt pins a flexible version
  range (not an exact pin) specifically so `pip install` always picks up
  the latest compatible release and self-heals from this class of
  breakage without requiring a code change here.

No required GitHub Secrets.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

# 100-nanosecond units → seconds conversion factor
_HNS_TO_SEC = 1e-7

_FEMALE_VOICES: List[str] = [
    "en-US-AriaNeural",
    "en-US-JennyNeural",
    "en-GB-SoniaNeural",
]

_MALE_VOICES: List[str] = [
    "en-US-GuyNeural",
    "en-US-ChristopherNeural",
    "en-GB-RyanNeural",
]

# A 403 on the WSS handshake means the pinned edge-tts package version is
# using a stale TrustedClientToken — retrying within the same process with
# the same package version will fail identically every time.
_STALE_TOKEN_PATTERNS = [
    r"\b403\b", r"\binvalid response status\b", r"\btrustedclienttoken\b",
]


def _matches_any(patterns, text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


class EdgeTTSProvider(BaseProvider):
    """
    Microsoft Edge-TTS free provider.
    Always available (no secret required, no quota).
    Uses asyncio.run() internally since edge-tts is async-first.
    """

    provider_name = "edge_tts"
    is_free_tier = True
    cascade_category = "tts"

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Always True — edge-tts has no API key and no quota."""
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            return False

    # ── Core execution ────────────────────────────────────────────────────────

    def execute(self, **kwargs: Any) -> ProviderResult:
        """
        kwargs expected
        ───────────────
        text          str  — narration text to synthesise
        voice_id      str  — if provided and looks like an edge-tts voice name,
                             use it directly; otherwise resolve from gender hint
        voice_gender  str  — "female" or "male" (used when voice_id is absent
                             or is an ElevenLabs UUID, not an edge-tts name)
        """
        text: str = kwargs.get("text", "").strip()
        requested_voice: str = kwargs.get("voice_id", "")
        gender: str = kwargs.get("voice_gender", "female").lower()

        if not text:
            return ProviderResult.failure(
                self.provider_name, "Empty text received.", retriable=False
            )

        # Resolve edge-tts voice name
        voice = self._resolve_voice(requested_voice, gender)

        try:
            audio_bytes, word_boundaries = asyncio.run(
                self._synthesise(text=text, voice=voice)
            )
        except RuntimeError:
            # Already inside an event loop (rare in GitHub Actions but handle it)
            loop = asyncio.new_event_loop()
            try:
                audio_bytes, word_boundaries = loop.run_until_complete(
                    self._synthesise(text=text, voice=voice)
                )
            finally:
                loop.close()
        except Exception as exc:
            err_lower = str(exc).lower()
            if _matches_any(_STALE_TOKEN_PATTERNS, err_lower):
                logger.error(
                    "edge_tts_stale_trusted_client_token",
                    error=str(exc),
                    action_required=(
                        "The installed edge-tts package version is using an "
                        "outdated WSS TrustedClientToken that Microsoft has "
                        "since rotated. Run: pip install --upgrade edge-tts "
                        "and confirm requirements.txt pins a recent, flexible "
                        "version range (e.g. edge-tts>=6.1.19,<7.0.0), not an "
                        "exact stale version."
                    ),
                )
                return ProviderResult.failure(
                    self.provider_name,
                    f"edge-tts synthesis error (stale TrustedClientToken — "
                    f"package upgrade required): {exc}",
                    retriable=False,
                )
            return ProviderResult.failure(
                self.provider_name, f"edge-tts synthesis error: {exc}"
            )

        if not audio_bytes:
            return ProviderResult.failure(
                self.provider_name, "edge-tts returned empty audio."
            )

        alignment = self._build_alignment(word_boundaries) if word_boundaries else None
        char_count = len(text)

        data: Dict[str, Any] = {
            "audio_bytes": audio_bytes,
            "alignment": alignment,
            "voice_id": voice,
            "char_count": char_count,
            "format": "mp3",
        }
        meta: Dict[str, Any] = {
            "provider": self.provider_name,
            "voice": voice,
            "char_count": char_count,
            "has_alignment": alignment is not None,
            "word_count": len(word_boundaries),
        }
        logger.info(
            "edge_tts_success",
            voice=voice,
            char_count=char_count,
            words=len(word_boundaries),
        )
        return ProviderResult(
            success=True,
            data=data,
            provider_used=self.provider_name,
            metadata=meta,
        )

    # ── Async synthesis ───────────────────────────────────────────────────────

    @staticmethod
    async def _synthesise(
        text: str, voice: str
    ) -> Tuple[bytes, List[Dict]]:
        """
        Stream audio and collect WordBoundary events.
        Returns (audio_bytes, word_boundaries).
        """
        import edge_tts

        communicate = edge_tts.Communicate(text=text, voice=voice)
        audio_chunks: List[bytes] = []
        word_boundaries: List[Dict] = []

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_boundaries.append(
                    {
                        "word": chunk.get("text", ""),
                        "offset_sec": chunk.get("offset", 0) * _HNS_TO_SEC,
                        "duration_sec": chunk.get("duration", 0) * _HNS_TO_SEC,
                    }
                )

        return b"".join(audio_chunks), word_boundaries

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_voice(requested_voice: str, gender: str) -> str:
        """
        Return an edge-tts voice name.
        If requested_voice looks like a valid edge-tts voice (contains 'Neural'),
        use it directly.  Otherwise pick the primary gender voice.
        """
        if requested_voice and "Neural" in requested_voice:
            return requested_voice
        return _FEMALE_VOICES[0] if gender == "female" else _MALE_VOICES[0]

    @staticmethod
    def _build_alignment(word_boundaries: List[Dict]) -> Dict:
        """
        Convert edge-tts WordBoundary events into the shared alignment schema
        used by ElevenLabs providers so the subtitle engine is provider-agnostic.

        Schema:
        {
          "type":        "word",
          "characters":  ["The", "mantis", "shrimp", ...],  (words, not chars)
          "start_times": [0.0, 0.35, 0.72, ...],
          "end_times":   [0.34, 0.71, 1.05, ...],
        }
        """
        words: List[str] = []
        starts: List[float] = []
        ends: List[float] = []

        for wb in word_boundaries:
            word = wb.get("word", "").strip()
            if not word:
                continue
            start = wb["offset_sec"]
            end = start + wb["duration_sec"]
            words.append(word)
            starts.append(round(start, 4))
            ends.append(round(end, 4))

        return {
            "type": "word",
            "characters": words,
            "start_times": starts,
            "end_times": ends,
        }
