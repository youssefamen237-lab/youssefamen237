from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import List, Optional

from .base import AudioPick, MusicProviderBase

logger = logging.getLogger(__name__)


class LocalMusicProvider(MusicProviderBase):
    key = "music_local"

    def __init__(self, *, rng: random.Random, user_dir: Path, assets_dir: Path) -> None:
        self.rng = rng
        self.user_dir = user_dir
        self.assets_dir = assets_dir

    def _list_audio(self, root: Path) -> List[Path]:
        if not root.exists():
            return []
        exts = {".mp3", ".wav", ".ogg", ".m4a"}
        files: List[Path] = []
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                files.append(p)
        return sorted(files)

    def pick(self, *, duration_seconds: float) -> Optional[AudioPick]:
        candidates = self._list_audio(self.user_dir) + self._list_audio(self.assets_dir)
        if not candidates:
            return None
        path = self.rng.choice(candidates)
        return AudioPick(path=path, asset_id=path.stem, provider_key=self.key)
