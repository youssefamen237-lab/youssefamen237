from __future__ import annotations

import logging
import os
import sys
from typing import Optional


def setup_logging(level: Optional[str] = None) -> None:
    lvl = (level or os.getenv("LOG_LEVEL", "INFO")).upper().strip()
    if lvl not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        lvl = "INFO"

    logging.basicConfig(
        level=getattr(logging, lvl),
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
