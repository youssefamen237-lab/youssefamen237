from __future__ import annotations

import os
import sys
import time


class Log:
    def __init__(self) -> None:
        self._start = time.time()
        self._debug = os.getenv("LOG_LEVEL", "INFO").upper() == "DEBUG"

    def _ts(self) -> str:
        elapsed = time.time() - self._start
        return f"{elapsed:8.2f}s"

    def info(self, msg: str) -> None:
        sys.stdout.write(f"[{self._ts()}] {msg}\n")
        sys.stdout.flush()

    def warn(self, msg: str) -> None:
        sys.stdout.write(f"[{self._ts()}] WARN: {msg}\n")
        sys.stdout.flush()

    def debug(self, msg: str) -> None:
        if not self._debug:
            return
        sys.stdout.write(f"[{self._ts()}] DEBUG: {msg}\n")
        sys.stdout.flush()
