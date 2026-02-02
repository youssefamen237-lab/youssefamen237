from __future__ import annotations

import asyncio
import os
from pathlib import Path

from ..utils.ffmpeg import run_ffmpeg
from ..utils.retry import retry
from .base import TTSEngine, TTSError, TTSResult


class EdgeTTS(TTSEngine):
    name = "edge-tts"

    def __init__(
        self,
        *,
        voice_env: str = "EDGE_TTS_VOICE",
        rate_env: str = "EDGE_TTS_RATE",
        pitch_env: str = "EDGE_TTS_PITCH",
    ) -> None:
        self.voice_env = voice_env
        self.rate_env = rate_env
        self.pitch_env = pitch_env

    def available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except Exception:
            return False

    def synthesize(self, text: str, out_wav: Path) -> TTSResult:
        try:
            import edge_tts
        except Exception as e:
            raise TTSError(f"edge-tts import failed: {e}")

        voice = (os.getenv(self.voice_env) or "en-US-GuyNeural").strip()
        rate = (os.getenv(self.rate_env) or "-5%").strip()
        pitch = (os.getenv(self.pitch_env) or "+0Hz").strip()

        out_wav.parent.mkdir(parents=True, exist_ok=True)
        mp3_path = out_wav.with_suffix(".edge.mp3")

        async def _run() -> None:
            communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
            await communicate.save(str(mp3_path))

        def _call() -> None:
            try:
                asyncio.run(_run())
            except RuntimeError:
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(_run())
                finally:
                    loop.close()
            if not mp3_path.exists() or mp3_path.stat().st_size < 1024:
                raise TTSError("edge-tts returned empty audio")

        retry(_call, tries=3, base_delay_s=1.2, max_delay_s=12.0)

        run_ffmpeg(
            [
                "-i",
                str(mp3_path),
                "-ar",
                "44100",
                "-ac",
                "2",
                str(out_wav),
            ]
        )

        return TTSResult(wav_path=out_wav, engine=self.name)
