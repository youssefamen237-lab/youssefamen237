\
from __future__ import annotations

import logging
from typing import Optional

from rich.logging import RichHandler


_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    """Configure process-wide logging once."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_time=True, show_level=True, show_path=False)],
    )
    _CONFIGURED = True


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    setup_logging(level or "INFO")
    logger = logging.getLogger(name)
    if level:
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger
