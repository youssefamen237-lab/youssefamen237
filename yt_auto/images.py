from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageFilter

from yt_auto.config import Config
from yt_auto.utils import ensure_dir


def pick_background(cfg: Config, seed: int) -> Path:
    bg_dir = cfg.backgrounds_dir
    if bg_dir.exists():
        imgs = []
        for p in bg_dir.iterdir():
            if not p.is_file():
                continue
            if p.name.startswith("."):
                continue
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                imgs.append(p)
        if imgs:
            r = random.Random(seed)
            return r.choice(imgs)

    ensure_dir(cfg.out_dir)
    out = cfg.out_dir / f"generated_bg_{seed}.jpg"
    _generate_bg(out, cfg.short_w, cfg.short_h, seed)
    return out


def _generate_bg(out_path: Path, w: int, h: int, seed: int) -> None:
    r = random.Random(seed)
    c1 = (r.randint(0, 60), r.randint(0, 60), r.randint(0, 60))
    c2 = (r.randint(120, 220), r.randint(120, 220), r.randint(120, 220))
    img = Image.new("RGB", (w, h), c1)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        rr = int(c1[0] * (1 - t) + c2[0] * t)
        gg = int(c1[1] * (1 - t) + c2[1] * t)
        bb = int(c1[2] * (1 - t) + c2[2] * t)
        for x in range(w):
            px[x, y] = (rr, gg, bb)
    img = img.filter(ImageFilter.GaussianBlur(radius=6))
    img.save(out_path, quality=90)
