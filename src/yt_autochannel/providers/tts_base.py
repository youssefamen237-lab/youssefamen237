from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class TTSResult:
    audio_path: Path
    duration_s: float
    provider: str
    voice: str


class TTSProvider(Protocol):
    name: str

    def synthesize(self, text: str, voice: str, out_path: Path, timeout_s: int = 60) -> TTSResult:
        ...
