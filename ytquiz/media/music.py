from __future__ import annotations

import random
from pathlib import Path

from ytquiz.utils import ensure_dir


SUPPORTED_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def pick_music_track(rng: random.Random, music_dir: Path) -> Path | None:
    ensure_dir(music_dir)
    tracks = [p for p in music_dir.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_AUDIO_EXTS]
    if not tracks:
        return None
    return rng.choice(tracks)
