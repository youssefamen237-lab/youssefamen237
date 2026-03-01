"""
utils/logger.py – Centralised Loguru configuration
"""
from __future__ import annotations
import sys
from pathlib import Path
from loguru import logger

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def configure_logger() -> None:
    logger.remove()
    # Stdout (GitHub Actions sees this in the workflow run log)
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level="DEBUG",
        colorize=True,
    )
    # Rotating file log (kept inside the runner workspace)
    logger.add(
        LOG_DIR / "quizzaro_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="7 days",
        level="DEBUG",
        encoding="utf-8",
    )
