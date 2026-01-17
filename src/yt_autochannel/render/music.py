from __future__ import annotations

import random
from pathlib import Path
from typing import List, Optional

from ..utils.subprocesses import run_cmd


def ensure_music(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    existing = [p for p in folder.iterdir() if p.suffix.lower() in {".mp3", ".wav", ".m4a"}]
    if existing:
        return
    # Generate a simple royalty-free synthetic bed (sine+triangle mix)
    out = folder / "bed1.mp3"
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=220:duration=60",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=330:duration=60",
        "-filter_complex",
        "[0:a][1:a]amix=inputs=2:normalize=0,volume=0.18",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "6",
        str(out),
    ]
    run_cmd(cmd, timeout=60, check=True)


def list_music(folder: Path) -> List[Path]:
    if not folder.exists():
        return []
    return sorted([p for p in folder.iterdir() if p.suffix.lower() in {".mp3", ".wav", ".m4a"}])


def pick_music(folder: Path, avoid_last: Optional[str] = None) -> Optional[Path]:
    tracks = list_music(folder)
    if not tracks:
        return None
    if avoid_last:
        tracks2 = [t for t in tracks if t.name != avoid_last]
        if tracks2:
            tracks = tracks2
    return random.choice(tracks)
