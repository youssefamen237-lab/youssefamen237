from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from ..utils.proc import run_cmd

logger = logging.getLogger(__name__)


def ffprobe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = run_cmd(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr.strip()[:1000]}")
    try:
        return float(proc.stdout.strip())
    except Exception:
        raise RuntimeError(f"ffprobe duration parse error: {proc.stdout.strip()}")


def run_ffmpeg(cmd: List[str], *, timeout: Optional[int] = None) -> None:
    proc = run_cmd(cmd, timeout=timeout)
    if proc.returncode != 0:
        logger.error("ffmpeg failed: %s", " ".join(cmd[:6]))
        raise RuntimeError(proc.stderr.strip()[-4000:])
