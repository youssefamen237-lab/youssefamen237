\
import logging
import os
from pathlib import Path
from typing import Optional

from .settings import REPO_ROOT


def setup_logging(log_name: str, level: Optional[str] = None) -> None:
    logs_dir = REPO_ROOT / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    level_name = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    lvl = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(lvl)
    logger.handlers.clear()

    fmt = logging.Formatter(
        fmt="%(asctime)sZ | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    sh = logging.StreamHandler()
    sh.setLevel(lvl)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    fh_path = logs_dir / f"{log_name}.log"
    fh = logging.FileHandler(fh_path, encoding="utf-8")
    fh.setLevel(lvl)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
