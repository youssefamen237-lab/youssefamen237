from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssetPick:
    path: Path
    asset_id: str
    provider_key: str


@dataclass(frozen=True)
class AudioPick:
    path: Path
    asset_id: str
    provider_key: str


@dataclass(frozen=True)
class TTSResult:
    path: Path
    provider_key: str
    voice: str


class ProviderBase:
    key: str

    def is_available(self) -> bool:
        return True


class TTSProviderBase(ProviderBase):
    def synthesize(self, text: str, voice: str, out_path: Path) -> TTSResult:
        raise NotImplementedError


class BackgroundProviderBase(ProviderBase):
    def pick(self) -> Optional[AssetPick]:
        raise NotImplementedError


class MusicProviderBase(ProviderBase):
    def pick(self, *, duration_seconds: float) -> Optional[AudioPick]:
        raise NotImplementedError
