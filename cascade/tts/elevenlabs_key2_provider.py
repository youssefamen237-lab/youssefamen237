"""
cascade/tts/elevenlabs_key2_provider.py

ElevenLabs TTS — Secondary API Key (ELEVEN_API_KEY_2)

Inherits all logic from ElevenLabsBaseProvider defined in
elevenlabs_key1_provider.py.  The only difference is the secret name
and the key_index used for Redis quota tracking.

Required GitHub Secret
──────────────────────
  ELEVEN_API_KEY_2
"""

from __future__ import annotations

from cascade.tts.elevenlabs_key1_provider import ElevenLabsBaseProvider


class ElevenLabsKey2Provider(ElevenLabsBaseProvider):
    """ElevenLabs TTS using the secondary API key (ELEVEN_API_KEY_2)."""
    provider_name = "elevenlabs_key2"
    _key_env = "ELEVEN_API_KEY_2"
    _key_index = 2
