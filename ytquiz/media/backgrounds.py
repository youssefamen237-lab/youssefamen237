from __future__ import annotations

import random
from pathlib import Path

from PIL import Image

from ytquiz.utils import ensure_dir


SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def pick_background(
    *,
    rng: random.Random,
    backgrounds_dir: Path,
    out_dir: Path,
    width: int,
    height: int,
) -> tuple[Path, str]:
    ensure_dir(backgrounds_dir)
    ensure_dir(out_dir)

    files = [p for p in backgrounds_dir.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]
    if files:
        src = rng.choice(files)
        out = out_dir / f"bg_{src.stem}_{width}x{height}.jpg"
        _prepare_image(src, out, width, height)
        return out, "folder"

    out = out_dir / f"bg_proc_{width}x{height}.jpg"
    _procedural_background(rng, out, width, height)
    return out, "procedural"


def _prepare_image(src: Path, out: Path, width: int, height: int) -> None:
    img = Image.open(src).convert("RGB")
    img = _fit_cover(img, width, height)
    img.save(out, format="JPEG", quality=92, optimize=True)


def _fit_cover(img: Image.Image, width: int, height: int) -> Image.Image:
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        return img.resize((width, height))
    scale = max(width / iw, height / ih)
    nw = int(iw * scale)
    nh = int(ih * scale)
    img = img.resize((nw, nh))
    x0 = (nw - width) // 2
    y0 = (nh - height) // 2
    return img.crop((x0, y0, x0 + width, y0 + height))


def _procedural_background(rng: random.Random, out: Path, width: int, height: int) -> None:
    img = Image.new("RGB", (width, height))
    base = (rng.randint(10, 40), rng.randint(10, 40), rng.randint(10, 40))
    accent = (rng.randint(120, 200), rng.randint(120, 200), rng.randint(120, 200))

    px = img.load()
    for y in range(height):
        t = y / max(1, height - 1)
        for x in range(width):
            u = x / max(1, width - 1)
            mix = 0.35 * t + 0.65 * u
            r = int(base[0] * (1 - mix) + accent[0] * mix)
            g = int(base[1] * (1 - mix) + accent[1] * mix)
            b = int(base[2] * (1 - mix) + accent[2] * mix)
            n = rng.randint(-18, 18)
            px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))

    img.save(out, format="JPEG", quality=92, optimize=True)
