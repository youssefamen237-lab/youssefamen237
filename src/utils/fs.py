from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

VIDEO_EXTS = {".mp4", ".mov", ".mkv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def list_files(dir_path: str | Path, exts: Sequence[str] | set[str]) -> List[Path]:
    p = Path(dir_path)
    if not p.exists():
        return []
    exts_set = set(str(e).lower() for e in exts)
    out: List[Path] = []
    for child in p.iterdir():
        if child.is_file() and child.suffix.lower() in exts_set:
            out.append(child)
    return sorted(out)


def atomic_write_text(path: str | Path, content: str, encoding: str = "utf-8") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(content, encoding=encoding)
    os.replace(tmp, p)
