\
import json
import subprocess
from pathlib import Path
from typing import Optional


def ffprobe_duration_seconds(path: Path) -> Optional[float]:
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "json",
            str(path),
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, check=True)
        doc = json.loads(p.stdout)
        streams = doc.get("streams") or []
        if not streams:
            return None
        dur = streams[0].get("duration")
        if dur is None:
            return None
        return float(dur)
    except Exception:
        try:
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
            p = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(p.stdout.strip())
        except Exception:
            return None
