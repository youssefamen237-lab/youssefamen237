from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Sequence


class FFmpegError(RuntimeError):
    pass


def ensure_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FFmpegError("ffmpeg not found in PATH")
    return exe


def run_ffmpeg(args: Sequence[str], *, cwd: Path | None = None) -> None:
    exe = ensure_ffmpeg()
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", *list(args)]
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    if p.returncode != 0:
        msg = (p.stderr or "").strip() or (p.stdout or "").strip()
        raise FFmpegError(f"ffmpeg failed ({p.returncode}): {msg}")
