from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CmdResult:
    cmd: List[str]
    returncode: int
    stdout: str
    stderr: str


def run_cmd(cmd: List[str], timeout: Optional[int] = None, check: bool = True) -> CmdResult:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    res = CmdResult(cmd=cmd, returncode=proc.returncode, stdout=proc.stdout or "", stderr=proc.stderr or "")
    if check and proc.returncode != 0:
        raise RuntimeError(
            "Command failed ({}): {}\nSTDOUT:\n{}\nSTDERR:\n{}".format(
                proc.returncode,
                " ".join(cmd),
                res.stdout,
                res.stderr,
            )
        )
    return res
