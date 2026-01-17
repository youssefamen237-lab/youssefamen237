from __future__ import annotations

import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PIL import Image


def ensure_backgrounds(folder: Path, min_count: int = 20) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    existing = [p for p in folder.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    if len(existing) >= min_count:
        return
    # generate simple gradient backgrounds (royalty-free, generated)
    for i in range(len(existing), min_count):
        w, h = 1920, 1080
        img = Image.new("RGB", (w, h))
        r1, g1, b1 = [random.randint(20, 200) for _ in range(3)]
        r2, g2, b2 = [min(255, c + random.randint(20, 80)) for c in (r1, g1, b1)]
        px = img.load()
        for y in range(h):
            t = y / (h - 1)
            r = int(r1 * (1 - t) + r2 * t)
            g = int(g1 * (1 - t) + g2 * t)
            b = int(b1 * (1 - t) + b2 * t)
            for x in range(w):
                px[x, y] = (r, g, b)
        out = folder / f"bg_{i:03d}.jpg"
        img.save(out, quality=92)


def list_backgrounds(folder: Path) -> List[Path]:
    if not folder.exists():
        return []
    bgs = [p for p in folder.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    bgs.sort()
    return bgs


def pick_background(folder: Path, db=None, cooldown_last_n: int = 6) -> Path:
    bgs = list_backgrounds(folder)
    if not bgs:
        ensure_backgrounds(folder)
        bgs = list_backgrounds(folder)
    recent: List[str] = []
    if db is not None:
        try:
            rows = db.list_recent_videos(days=30, limit=200)
            for r in rows:
                if r["bg_image_id"]:
                    recent.append(str(r["bg_image_id"]))
        except Exception:
            recent = []
    recent = recent[:cooldown_last_n]
    candidates = [p for p in bgs if p.name not in set(recent)]
    if not candidates:
        candidates = bgs
    return random.choice(candidates)
