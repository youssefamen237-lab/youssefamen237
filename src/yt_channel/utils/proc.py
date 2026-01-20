from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional


def run_cmd(cmd: List[str], *, cwd: Optional[Path] = None, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
