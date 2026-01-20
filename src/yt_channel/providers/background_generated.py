from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

from .base import AssetPick, BackgroundProviderBase

logger = logging.getLogger(__name__)


class GeneratedBackgroundProvider(BackgroundProviderBase):
    key = "bg_generated"

    def __init__(self, *, rng: random.Random, out_dir: Path) -> None:
        self.rng = rng
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _existing(self) -> List[Path]:
        exts = {".jpg", ".jpeg", ".png"}
        files: List[Path] = []
        for p in self.out_dir.glob("*.png"):
            if p.is_file() and p.suffix.lower() in exts:
                files.append(p)
        return sorted(files)

    def _rand_color(self) -> Tuple[int, int, int]:
        return (self.rng.randint(30, 220), self.rng.randint(30, 220), self.rng.randint(30, 220))

    def _make_one(self, idx: int, size: Tuple[int, int] = (1920, 1080)) -> Path:
        w, h = size
        c1 = self._rand_color()
        c2 = self._rand_color()
        img = Image.new("RGB", (w, h), c1)
        draw = ImageDraw.Draw(img)
        # Simple diagonal gradient + soft circles
        for y in range(h):
            t = y / max(h - 1, 1)
            r = int(c1[0] * (1 - t) + c2[0] * t)
            g = int(c1[1] * (1 - t) + c2[1] * t)
            b = int(c1[2] * (1 - t) + c2[2] * t)
            draw.line([(0, y), (w, y)], fill=(r, g, b))
        for _ in range(18):
            cx = self.rng.randint(0, w)
            cy = self.rng.randint(0, h)
            radius = self.rng.randint(80, 260)
            cc = self._rand_color()
            alpha = self.rng.randint(20, 60)
            overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            od.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                fill=(cc[0], cc[1], cc[2], alpha),
            )
            img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        path = self.out_dir / f"gen_bg_{idx:03d}.png"
        img.save(path, format="PNG", optimize=True)
        return path

    def ensure_pool(self, min_count: int = 10) -> None:
        existing = self._existing()
        if len(existing) >= min_count:
            return
        start = len(existing)
        for i in range(start, min_count):
            self._make_one(i)

    def pick(self) -> Optional[AssetPick]:
        self.ensure_pool(min_count=10)
        files = self._existing()
        if not files:
            return None
        path = self.rng.choice(files)
        return AssetPick(path=path, asset_id=path.stem, provider_key=self.key)
