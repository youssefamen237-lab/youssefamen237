from __future__ import annotations

import logging
from pathlib import Path

from .base import TTSError, TTSResult
from .edge import EdgeTTS
from .elevenlabs import ElevenLabs
from .espeak import Espeak, EspeakNG
from .festival import Festival

log = logging.getLogger(__name__)


class TTSManager:
    def __init__(self) -> None:
        self.engines = [
            ElevenLabs(),
            EdgeTTS(),
            EspeakNG(),
            Espeak(),
            Festival(),
        ]

    def synthesize(self, text: str, out_wav: Path) -> TTSResult:
        last: Exception | None = None
        for eng in self.engines:
            try:
                if not eng.available():
                    continue
                res = eng.synthesize(text, out_wav)
                return res
            except Exception as e:
                last = e
                log.warning("TTS engine failed (%s): %s", eng.name, str(e))
        raise TTSError(f"All TTS engines failed: {last}")
