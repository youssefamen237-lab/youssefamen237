from __future__ import annotations

from pathlib import Path


def pick_music_track(rng, music_dir: Path) -> Path | None:
    if music_dir is None:
        return None
    if not music_dir.exists():
        return None

    exts = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
    files: list[Path] = []
    for p in music_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            files.append(p)

    if not files:
        return None

    return rng.choice(files)
