\
import logging
import random
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageFilter

from .settings import REPO_ROOT

logger = logging.getLogger(__name__)


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}


def repo_path(rel: str) -> Path:
    return (REPO_ROOT / rel).resolve()


def list_files(directory: Path, exts: set) -> List[Path]:
    if not directory.exists():
        return []
    out: List[Path] = []
    for p in directory.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            out.append(p)
    return out


def pick_random_image(images_dir: Path) -> Optional[Path]:
    files = list_files(images_dir, IMAGE_EXTS)
    if not files:
        return None
    return random.choice(files)


def pick_random_music(music_dir: Path) -> Optional[Path]:
    files = list_files(music_dir, AUDIO_EXTS)
    if not files:
        return None
    return random.choice(files)


def make_gradient_background(size: Tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", (w, h), (15, 15, 15))
    px = img.load()
    r1, g1, b1 = [random.randint(10, 80) for _ in range(3)]
    r2, g2, b2 = [random.randint(120, 220) for _ in range(3)]
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img.filter(ImageFilter.GaussianBlur(radius=10))


def load_blurred_background(images_dir: Path, size: Tuple[int, int], blur_radius: int) -> Image.Image:
    p = pick_random_image(images_dir)
    if not p:
        return make_gradient_background(size)

    try:
        with Image.open(p) as im:
            im = im.convert("RGB")
            w, h = size
            im_ratio = im.width / im.height
            target_ratio = w / h
            if im_ratio > target_ratio:
                new_h = h
                new_w = int(im_ratio * new_h)
            else:
                new_w = w
                new_h = int(new_w / im_ratio)
            im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
            left = max(0, (new_w - w) // 2)
            top = max(0, (new_h - h) // 2)
            im = im.crop((left, top, left + w, top + h))
            im = im.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            return im
    except Exception as e:
        logger.warning("Failed to load background image %s: %s", p, e)
        return make_gradient_background(size)
