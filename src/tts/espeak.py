from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .base import TTSEngine, TTSError, TTSResult


class EspeakNG(TTSEngine):
    name = "espeak-ng"

    def __init__(self, *, voice: str = "en-us", speed: int = 170) -> None:
        self.voice = voice
        self.speed = speed

    def available(self) -> bool:
        return shutil.which("espeak-ng") is not None

    def synthesize(self, text: str, out_wav: Path) -> TTSResult:
        exe = shutil.which("espeak-ng")
        if not exe:
            raise TTSError("espeak-ng not found")
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            exe,
            "-v",
            self.voice,
            "-s",
            str(self.speed),
            "-w",
            str(out_wav),
            text,
        ]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0 or not out_wav.exists():
            raise TTSError(f"espeak-ng failed: {(p.stderr or p.stdout).strip()}")
        return TTSResult(wav_path=out_wav, engine=self.name)


class Espeak(TTSEngine):
    name = "espeak"

    def __init__(self, *, voice: str = "en-us", speed: int = 170) -> None:
        self.voice = voice
        self.speed = speed

    def available(self) -> bool:
        return shutil.which("espeak") is not None

    def synthesize(self, text: str, out_wav: Path) -> TTSResult:
        exe = shutil.which("espeak")
        if not exe:
            raise TTSError("espeak not found")
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            exe,
            "-v",
            self.voice,
            "-s",
            str(self.speed),
            "-w",
            str(out_wav),
            text,
        ]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0 or not out_wav.exists():
            raise TTSError(f"espeak failed: {(p.stderr or p.stdout).strip()}")
        return TTSResult(wav_path=out_wav, engine=self.name)
