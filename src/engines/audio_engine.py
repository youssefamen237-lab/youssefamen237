from pathlib import Path

import requests
from gtts import gTTS

from core.config import CONFIG
from utils.retry import with_retry


class AudioEngine:
    def synthesize(self, text: str, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)

        def eleven() -> Path:
            if not CONFIG.eleven_api_key:
                raise RuntimeError("No ElevenLabs key")
            r = requests.post(
                "https://api.elevenlabs.io/v1/text-to-speech/EXAVITQu4vr4xnSDxMaL",
                headers={"xi-api-key": CONFIG.eleven_api_key, "Content-Type": "application/json"},
                json={"text": text, "model_id": "eleven_multilingual_v2"},
                timeout=60,
            )
            r.raise_for_status()
            out_path.write_bytes(r.content)
            return out_path

        def gtts_fallback() -> Path:
            tts = gTTS(text=text, lang="en")
            tts.save(str(out_path))
            return out_path

        return with_retry(lambda: eleven(), retries=1, fallback=gtts_fallback)
