"""
utils/logger.py
===============
Centralised logging configuration for MindCraft Psychology.

Every module gets a logger via:
    from utils.logger import get_logger
    logger = get_logger(__name__)

Features
--------
- Rich console handler  : colour-coded, human-readable output in terminal
                          and GitHub Actions logs.
- Rotating file handler : persists logs to logs/pipeline.log with automatic
                          rotation at 5 MB, keeping the last 3 archives.
- Single initialisation : the root "mindcraft" logger is configured once;
                          subsequent get_logger() calls return child loggers
                          that inherit the handlers — no duplicate output.
- Level from env        : LOG_LEVEL in .env controls verbosity without
                          touching code (DEBUG | INFO | WARNING | ERROR).
"""

import logging
import logging.handlers
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from config.settings import LOG_FILE, LOG_LEVEL

# ── Constants ──────────────────────────────────────────────────────────────
ROOT_LOGGER_NAME = "mindcraft"
LOG_FORMAT_FILE  = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT  = "%Y-%m-%dT%H:%M:%SZ"
MAX_BYTES        = 5 * 1024 * 1024   # 5 MB per log file
BACKUP_COUNT     = 3                  # keep 3 rotated archives

# ── Internal state — initialised once ─────────────────────────────────────
_initialised: bool = False


def _init_root_logger() -> None:
    """
    Configure the root 'mindcraft' logger exactly once.
    Called automatically by get_logger() on first use.
    """
    global _initialised
    if _initialised:
        return

    # Resolve numeric log level
    numeric_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.setLevel(numeric_level)

    # ── 1. Rich console handler ────────────────────────────────────────────
    console = Console(stderr=True, highlight=False)
    rich_handler = RichHandler(
        console=console,
        show_path=False,           # module path already in the logger name
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        log_time_format="%H:%M:%S",
    )
    rich_handler.setLevel(numeric_level)
    root.addHandler(rich_handler)

    # ── 2. Rotating file handler ───────────────────────────────────────────
    log_path = Path(LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_path,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(
        logging.Formatter(fmt=LOG_FORMAT_FILE, datefmt=LOG_DATE_FORMAT)
    )
    root.addHandler(file_handler)

    # Suppress noisy third-party loggers at WARNING unless debugging
    for noisy in ("httpx", "httpcore", "urllib3", "googleapiclient"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _initialised = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger namespaced under 'mindcraft.<name>'.

    Parameters
    ----------
    name : Typically __name__ from the calling module.
           e.g. 'core.script_generator' → logger 'mindcraft.core.script_generator'

    Usage
    -----
        from utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Pipeline started.")
        logger.warning("Gemini failed, falling back to Groq.")
        logger.error("Upload failed: %s", error_message)
    """
    _init_root_logger()

    # Strip the package root prefix if present so names stay clean
    # e.g. 'mindcraft_psychology.core.research' → 'core.research'
    clean_name = name.replace("mindcraft_psychology.", "")
    full_name  = f"{ROOT_LOGGER_NAME}.{clean_name}"
    return logging.getLogger(full_name)


def log_pipeline_start(mode: str) -> None:
    """Log a prominent pipeline start banner (visible in GitHub Actions)."""
    logger = get_logger("pipeline")
    logger.info("=" * 60)
    logger.info("MindCraft Psychology — Pipeline START  mode=%s", mode.upper())
    logger.info("=" * 60)


def log_pipeline_end(mode: str, success: bool, detail: str = "") -> None:
    """Log a prominent pipeline end banner."""
    logger = get_logger("pipeline")
    status = "SUCCESS" if success else "FAILED"
    logger.info("=" * 60)
    logger.info(
        "MindCraft Psychology — Pipeline END  mode=%s  status=%s  %s",
        mode.upper(), status, detail,
    )
    logger.info("=" * 60)
