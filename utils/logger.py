"""
utils/logger.py
Karma Vault Stories — Centralized Structured Logger
All engines import get_logger(__name__) for consistent, CI-safe output.
"""

import logging
import sys
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from config.settings import LOGS_DIR


class JSONLineFormatter(logging.Formatter):
    """
    Emits one JSON object per line. Structured logs are trivially parseable
    by GitHub Actions log streaming and any analytics dashboard.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts":       datetime.now(timezone.utc).isoformat(),
            "level":    record.levelname,
            "logger":   record.name,
            "msg":      record.getMessage(),
            "module":   record.module,
            "line":     record.lineno,
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        if hasattr(record, "extra"):
            entry.update(record.extra)
        return json.dumps(entry, ensure_ascii=False)


class HumanFormatter(logging.Formatter):
    """
    Human-readable format for GitHub Actions console output.
    Color-coded via ANSI codes (works in GHA log viewer).
    """
    COLORS = {
        "DEBUG":    "\033[36m",    # cyan
        "INFO":     "\033[32m",    # green
        "WARNING":  "\033[33m",    # yellow
        "ERROR":    "\033[31m",    # red
        "CRITICAL": "\033[35m",    # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        prefix = f"{color}[{record.levelname[0]}]{self.RESET}"
        return f"{prefix} {ts} [{record.name}] {record.getMessage()}"


def _build_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured in this process

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Console handler — human readable, INFO+
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(HumanFormatter())
    logger.addHandler(console_handler)

    # File handler — JSON lines, DEBUG+ (full detail for post-run analysis)
    try:
        log_file = LOGS_DIR / f"pipeline_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(JSONLineFormatter())
        logger.addHandler(file_handler)
    except OSError:
        # In extreme CI environments where filesystem is read-only — degrade gracefully
        pass

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Primary factory used by every engine module:
        from utils.logger import get_logger
        log = get_logger(__name__)
    """
    return _build_logger(name)


class PipelineRunLogger:
    """
    Tracks a single full pipeline run (one daily video).
    Persists a structured run summary to disk for analytics consumption.
    """

    def __init__(self, run_id: str):
        self.run_id   = run_id
        self.log      = get_logger("pipeline.run")
        self.started  = datetime.now(timezone.utc)
        self.events: list[dict] = []
        self.errors: list[dict] = []
        self.summary: dict = {
            "run_id":       run_id,
            "started_at":   self.started.isoformat(),
            "finished_at":  None,
            "status":       "running",
            "stages":       {},
        }

    def stage_start(self, stage: str) -> None:
        self.log.info(f"▶ STAGE START: {stage}")
        self.summary["stages"][stage] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
        }

    def stage_success(self, stage: str, data: Optional[dict] = None) -> None:
        self.log.info(f"✓ STAGE OK:    {stage}")
        self.summary["stages"][stage].update({
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            **(data or {}),
        })

    def stage_failure(self, stage: str, error: Exception, fatal: bool = False) -> None:
        tb = traceback.format_exc()
        self.log.error(f"✗ STAGE FAIL:  {stage} — {error}")
        self.errors.append({"stage": stage, "error": str(error), "traceback": tb})
        self.summary["stages"][stage].update({
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed",
            "error": str(error),
        })
        if fatal:
            self.finalize(status="failed")
            raise RuntimeError(f"Fatal pipeline failure at stage '{stage}': {error}") from error

    def record(self, key: str, value: Any) -> None:
        """Store a key result value in the run summary (e.g. video_id, title)."""
        self.summary[key] = value

    def finalize(self, status: str = "success") -> dict:
        self.summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.summary["status"] = status
        elapsed = (datetime.now(timezone.utc) - self.started).total_seconds()
        self.summary["elapsed_sec"] = round(elapsed, 1)

        # Persist run summary to logs dir
        out_path = LOGS_DIR / f"run_{self.run_id}.json"
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(self.summary, f, indent=2, ensure_ascii=False)
        except OSError as exc:
            self.log.warning(f"Could not write run summary to disk: {exc}")

        level = self.log.info if status == "success" else self.log.error
        level(f"Pipeline run {self.run_id} finished — status={status}, elapsed={elapsed:.0f}s")
        return self.summary
