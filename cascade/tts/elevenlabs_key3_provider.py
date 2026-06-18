"""
cascade/tts/elevenlabs_key3_provider.py

ElevenLabs TTS — Tertiary API Key (ELEVEN_API_KEY_3)

Inherits all logic from ElevenLabsBaseProvider defined in
elevenlabs_key1_provider.py.  The only difference is the secret name
and the key_index used for Redis quota tracking.

Required GitHub Secret
──────────────────────
  ELEVEN_API_KEY_3
"""

from __future__ import annotations

from cascade.tts.elevenlabs_key1_provider import ElevenLabsBaseProvider


class ElevenLabsKey3Provider(ElevenLabsBaseProvider):
    """ElevenLabs TTS using the tertiary API key (ELEVEN_API_KEY_3)."""
    provider_name = "elevenlabs_key3"
    _key_env = "ELEVEN_API_KEY_3"
    _key_index = 3
