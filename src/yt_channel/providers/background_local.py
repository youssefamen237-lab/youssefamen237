from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import List, Optional

from .base import AssetPick, BackgroundProviderBase

logger = logging.getLogger(__name__)


class LocalBackgroundProvider(BackgroundProviderBase):
    key = "bg_local"

    def __init__(self, *, rng: random.Random, user_dir: Path, assets_dir: Path) -> None:
        self.rng = rng
        self.user_dir = user_dir
        self.assets_dir = assets_dir

    def _list_images(self, root: Path) -> List[Path]:
        if not root.exists():
            return []
        exts = {".jpg", ".jpeg", ".png", ".webp"}
        files: List[Path] = []
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                files.append(p)
        return sorted(files)

    def pick(self) -> Optional[AssetPick]:
        candidates = self._list_images(self.user_dir) + self._list_images(self.assets_dir)
        if not candidates:
            return None
        path = self.rng.choice(candidates)
        asset_id = path.stem
        return AssetPick(path=path, asset_id=asset_id, provider_key=self.key)
