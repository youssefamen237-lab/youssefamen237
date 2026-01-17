from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts

from ..utils.media_utils import get_audio_duration_s
from .tts_base import TTSProvider, TTSResult


class EdgeTTS:
    name = "edge-tts"

    def synthesize(self, text: str, voice: str, out_path: Path, timeout_s: int = 60) -> TTSResult:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        text = text.strip()
        if not text:
            raise ValueError("TTS text is empty")

        async def _run() -> None:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(out_path))

        asyncio.run(asyncio.wait_for(_run(), timeout=timeout_s))
        duration = get_audio_duration_s(out_path)
        return TTSResult(audio_path=out_path, duration_s=duration, provider=self.name, voice=voice)
