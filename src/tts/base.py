from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class TTSError(RuntimeError):
    pass


@dataclass(frozen=True)
class TTSResult:
    wav_path: Path
    engine: str


class TTSEngine:
    name: str

    def available(self) -> bool:
        raise NotImplementedError

    def synthesize(self, text: str, out_wav: Path) -> TTSResult:
        raise NotImplementedError
