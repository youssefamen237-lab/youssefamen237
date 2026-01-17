from __future__ import annotations

import json
from pathlib import Path

from .subprocesses import run_cmd


def get_audio_duration_s(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    res = run_cmd(cmd, timeout=30, check=True)
    data = json.loads(res.stdout)
    dur = float(data["format"]["duration"])
    return dur
