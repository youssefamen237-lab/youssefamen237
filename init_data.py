"""
data/init_data.py – Quizzaro Data Initialiser
==============================================
Creates every JSON / directory that the pipeline reads and writes.
Run automatically by bootstrap.yml BEFORE main.py on the very first run.
Safe to re-run: all operations are idempotent (skip if file already exists
or if TinyDB table already has rows).

Files created / verified:
  data/
  ├── anti_duplicate.json        (TinyDB — questions / backgrounds / music tables)
  ├── publish_log.json           (list of uploaded Shorts, appended by uploader)
  ├── quota_log.json             (YouTube API daily quota tracker)
  ├── polls_log.json             (SHA-256 fingerprints of posted polls)
  ├── strategy_config.json       (strategy settings read by all modules)
  ├── sfx_cache/                 (Freesound SFX files cached here)
  ├── fonts/                     (Montserrat fonts downloaded here)
  ├── bg_cache/                  (B-roll video downloads)
  ├── music_cache/               (BGM audio downloads)
  ├── tts_temp/                  (per-job TTS scratch files)
  ├── render_tmp/                (per-job frame render scratch)
  ├── reports/                   (weekly Markdown analytics reports)
  └── logs/                      (rotating log files)

Also downloads the Montserrat font family from Google Fonts if missing.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import requests
from loguru import logger

DATA_DIR = Path("data")

# ── All subdirectories ────────────────────────────────────────────────────────
SUBDIRS = [
    DATA_DIR / "sfx_cache",
    DATA_DIR / "fonts",
    DATA_DIR / "bg_cache",
    DATA_DIR / "music_cache",
    DATA_DIR / "tts_temp",
    DATA_DIR / "render_tmp",
    DATA_DIR / "reports",
    DATA_DIR / "logs",
]

# ── Default strategy config ───────────────────────────────────────────────────
DEFAULT_STRATEGY_CONFIG = {
    "daily_video_count_min": 4,
    "daily_video_count_max": 8,
    "publish_hour_windows": [[7, 9], [12, 14], [18, 20], [21, 23]],
    "top_templates": [],
    "top_categories": [],
    "top_voice_gender": "mixed",
    "top_audiences": ["American", "British", "Canadian", "Australian"],
    "target_video_duration_range": [12.0, 16.0],
    "best_cta_indices": [],
    "underperforming_templates": [],
    "underperforming_categories": [],
    "last_updated": None,
    "total_shorts_analysed": 0,
    "channel_subscribers": 0,
    "monetization_progress": {
        "subscribers_needed": 1000,
        "watch_hours_needed": 4000,
        "current_subscribers": 0,
        "current_watch_hours": 0.0,
        "subscribers_remaining": 1000,
        "watch_hours_remaining": 4000.0,
        "sub_completion_pct": 0.0,
        "watch_hours_completion_pct": 0.0,
    },
}

# ── Montserrat font URLs (Google Fonts static CDN) ────────────────────────────
FONT_URLS = {
    "montserrat_bold.ttf":      "https://fonts.gstatic.com/s/montserrat/v26/JTUHjIg1_i6t8kCHKm4532VJOt5-QNFgpCvC73w5aXp-p7K4KLg.woff2",
    "montserrat_extrabold.ttf": "https://fonts.gstatic.com/s/montserrat/v26/JTUHjIg1_i6t8kCHKm4532VJOt5-QNFgpCu170w5aXp-p7K4KLg.woff2",
    "montserrat_regular.ttf":   "https://fonts.gstatic.com/s/montserrat/v26/JTUHjIg1_i6t8kCHKm4532VJOt5-QNFgpCtr7w5aXp-p7K4KLg.woff2",
}

# Fallback: direct TTF download from a reliable open mirror
FONT_TTF_URLS = {
    "montserrat_bold.ttf":      "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf",
    "montserrat_extrabold.ttf": "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-ExtraBold.ttf",
    "montserrat_regular.ttf":   "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Regular.ttf",
}


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for d in SUBDIRS:
        d.mkdir(parents=True, exist_ok=True)
    logger.info("[Init] Directories verified.")


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content, encoding="utf-8")
        logger.info(f"[Init] Created: {path}")
    else:
        logger.debug(f"[Init] Already exists: {path}")


def _init_json_files() -> None:
    # publish_log.json — empty list
    _write_if_missing(DATA_DIR / "publish_log.json", "[]")

    # quota_log.json — today's slate
    from datetime import datetime
    quota_default = json.dumps(
        {"date": datetime.utcnow().strftime("%Y-%m-%d"), "used": 0},
        indent=2
    )
    _write_if_missing(DATA_DIR / "quota_log.json", quota_default)

    # polls_log.json — empty list of SHA-256 fingerprints
    _write_if_missing(DATA_DIR / "polls_log.json", "[]")

    # strategy_config.json
    _write_if_missing(
        DATA_DIR / "strategy_config.json",
        json.dumps(DEFAULT_STRATEGY_CONFIG, indent=2, ensure_ascii=False),
    )

    # anti_duplicate.json — TinyDB creates its own structure; just touch it
    _write_if_missing(DATA_DIR / "anti_duplicate.json", "{}")

    logger.info("[Init] JSON files verified.")


def _download_font(name: str, dest: Path) -> bool:
    url = FONT_TTF_URLS.get(name)
    if not url:
        return False
    try:
        resp = requests.get(url, timeout=30, stream=True)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        logger.success(f"[Init] Font downloaded: {name}")
        return True
    except Exception as exc:
        logger.warning(f"[Init] Font download failed for {name}: {exc}")
        return False


def _init_fonts() -> None:
    fonts_dir = DATA_DIR / "fonts"
    for font_name in FONT_TTF_URLS:
        dest = fonts_dir / font_name
        if dest.exists() and dest.stat().st_size > 10_000:
            logger.debug(f"[Init] Font already cached: {font_name}")
            continue
        logger.info(f"[Init] Downloading font: {font_name} …")
        _download_font(font_name, dest)


def _verify_tinydb() -> None:
    """Touch the TinyDB file so TinyDB doesn't error on first open."""
    db_path = DATA_DIR / "anti_duplicate.json"
    try:
        from tinydb import TinyDB
        db = TinyDB(db_path)
        _ = db.table("questions")
        _ = db.table("backgrounds")
        _ = db.table("music")
        db.close()
        logger.info("[Init] TinyDB anti_duplicate.json verified.")
    except Exception as exc:
        logger.warning(f"[Init] TinyDB init warning: {exc}")


def run() -> None:
    """
    Main entry point.  Called by bootstrap.yml step before main.py.
    Also callable as: python -m data.init_data
    """
    logger.info("[Init] Starting data initialisation …")
    _ensure_dirs()
    _init_json_files()
    _init_fonts()
    _verify_tinydb()
    logger.success("[Init] ✅ All data files and directories are ready.")


if __name__ == "__main__":
    from utils.logger import configure_logger
    configure_logger()
    run()
