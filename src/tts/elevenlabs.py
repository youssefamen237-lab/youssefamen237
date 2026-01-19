from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import requests

from ..utils.ffmpeg import run_ffmpeg
from ..utils.retry import retry
from .base import TTSEngine, TTSError, TTSResult


class ElevenLabs(TTSEngine):
    name = "elevenlabs"

    def __init__(
        self,
        *,
        api_key_env: str = "ELEVEN_API_KEY",
        prefer_voices: Optional[list[str]] = None,
        stability: float = 0.40,
        clarity: float = 0.78,
        speed: float = 0.95,
    ) -> None:
        self.api_key_env = api_key_env
        self.prefer_voices = prefer_voices or ["Adam", "Josh", "Brian"]
        self.stability = float(stability)
        self.clarity = float(clarity)
        self.speed = float(speed)
        self._cached_voice_id: Optional[str] = None

    def _key(self) -> Optional[str]:
        k = os.getenv(self.api_key_env)
        if not k or not k.strip():
            return None
        return k.strip()

    def available(self) -> bool:
        return self._key() is not None

    def _pick_voice_id(self) -> str:
        if self._cached_voice_id:
            return self._cached_voice_id

        key = self._key()
        if not key:
            raise TTSError("ELEVEN_API_KEY missing")

        headers = {"xi-api-key": key}

        def _call() -> str:
            r = requests.get("https://api.elevenlabs.io/v1/voices", headers=headers, timeout=25)
            if r.status_code != 200:
                raise TTSError(f"ElevenLabs voices list failed: {r.status_code} {r.text}")
            data = r.json()
            voices = data.get("voices", [])
            if not isinstance(voices, list) or not voices:
                raise TTSError("ElevenLabs returned empty voices list")

            preferred = [v.strip().lower() for v in self.prefer_voices if v and v.strip()]
            for name in preferred:
                for it in voices:
                    if isinstance(it, dict) and isinstance(it.get("name"), str) and isinstance(it.get("voice_id"), str):
                        if it["name"].strip().lower() == name:
                            return it["voice_id"]

            for it in voices:
                if isinstance(it, dict) and isinstance(it.get("voice_id"), str):
                    vid = it["voice_id"].strip()
                    if vid:
                        return vid

            raise TTSError("No ElevenLabs voice_id available")

        vid = retry(_call, tries=3, base_delay_s=1.2, max_delay_s=12.0)
        self._cached_voice_id = vid
        return vid

    def synthesize(self, text: str, out_wav: Path) -> TTSResult:
        key = self._key()
        if not key:
            raise TTSError("ELEVEN_API_KEY missing")

        voice_id = self._pick_voice_id()

        out_wav.parent.mkdir(parents=True, exist_ok=True)
        mp3_path = out_wav.with_suffix(".eleven.mp3")

        headers = {
            "xi-api-key": key,
            "accept": "audio/mpeg",
            "content-type": "application/json",
        }

        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": max(0.0, min(1.0, self.stability)),
                "similarity_boost": max(0.0, min(1.0, self.clarity)),
                "use_speaker_boost": True,
            },
        }

        def _call() -> None:
            r = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers=headers,
                json=payload,
                timeout=60,
            )
            if r.status_code != 200:
                raise TTSError(f"ElevenLabs TTS failed: {r.status_code} {r.text}")
            mp3_path.write_bytes(r.content)
            if not mp3_path.exists() or mp3_path.stat().st_size < 1024:
                raise TTSError("ElevenLabs returned empty audio")

        retry(_call, tries=3, base_delay_s=1.4, max_delay_s=18.0)

        atempo = max(0.5, min(2.0, self.speed))

        run_ffmpeg(
            [
                "-i",
                str(mp3_path),
                "-ar",
                "44100",
                "-ac",
                "2",
                "-filter:a",
                f"atempo={atempo}",
                str(out_wav),
            ]
        )

        return TTSResult(wav_path=out_wav, engine=self.name)
