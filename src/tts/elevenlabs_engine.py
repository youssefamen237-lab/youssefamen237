from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger("elevenlabs_engine")


def synthesize(
    text: str,
    *,
    out_path: str | Path,
    model_id: str = "eleven_multilingual_v2",
    stability: float = 0.35,
    similarity_boost: float = 0.75,
    style: float = 0.2,
) -> Path:
    api_key = os.getenv("ELEVEN_API_KEY", "")
    voice_id = os.getenv("ELEVEN_VOICE_ID", "")
    if not api_key or not voice_id:
        raise RuntimeError("Missing ELEVEN_API_KEY or ELEVEN_VOICE_ID env vars")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "use_speaker_boost": True,
        },
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    out.write_bytes(r.content)
    return out
