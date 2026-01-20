from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..utils.proc import run_cmd
from .base import ProviderError, TTSProviderBase, TTSResult

logger = logging.getLogger(__name__)


class EspeakTTSProvider(TTSProviderBase):
    key = "tts_espeak"

    def is_available(self) -> bool:
        return shutil.which("espeak-ng") is not None or shutil.which("espeak") is not None

    def synthesize(self, text: str, voice: str, out_path: Path) -> TTSResult:
        out_path.parent.mkdir(parents=True, exist_ok=True)

        exe = shutil.which("espeak-ng") or shutil.which("espeak")
        if not exe:
            raise ProviderError("espeak not installed")

        # Map neural voice names to a basic espeak voice.
        espeak_voice = "en-us"
        cmd = [exe, "-v", espeak_voice, "-s", "165", "-w", str(out_path), text]

        proc = run_cmd(cmd)
        if proc.returncode != 0:
            raise ProviderError(f"espeak failed: {proc.stderr.strip()[:1000]}")

        if not out_path.exists() or out_path.stat().st_size < 1000:
            raise ProviderError("espeak produced empty audio")

        return TTSResult(path=out_path, provider_key=self.key, voice=espeak_voice)
