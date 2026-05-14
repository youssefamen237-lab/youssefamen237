"""
utils/file_manager.py
Karma Vault Stories — CI-Safe File & Workspace Manager
Handles all path operations, temp workspace creation, artifact persistence,
and emergency export logic. All paths resolve relative to GITHUB_WORKSPACE.
"""

import os
import json
import shutil
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from config.settings import (
    ROOT_DIR, DATA_DIR, STORY_BANK_DIR, ANALYTICS_DIR,
    HEURISTICS_DIR, EMERGENCY_EXPORT_DIR, LOGS_DIR,
    WORKSPACE_DIR,
)
from config.constants import (
    STORY_BANK_FILES, PUBLICATION_LOG_FILE,
    HEURISTICS_FILE, HEURISTICS_DEFAULT,
)
from utils.logger import get_logger

log = get_logger(__name__)


# ─────────────────────────────────────────────
# WORKSPACE SETUP
# ─────────────────────────────────────────────

def ensure_run_workspace(run_id: str) -> Path:
    """
    Creates an isolated working directory for one pipeline run.
    All temp assets (voice files, images, video drafts) live here.
    Cleared at end of run to conserve disk space on GHA runner.
    Returns the workspace Path.
    """
    ws = WORKSPACE_DIR / "run_workspaces" / run_id
    for sub in ["audio", "images", "video", "thumbnails", "cards"]:
        (ws / sub).mkdir(parents=True, exist_ok=True)
    log.debug(f"Run workspace created: {ws}")
    return ws


def cleanup_run_workspace(run_id: str, keep_final_outputs: bool = True) -> None:
    """
    Removes the run workspace. If keep_final_outputs=True (default),
    copies final MP4, short MP4, and thumbnail to emergency_export before wiping.
    """
    ws = WORKSPACE_DIR / "run_workspaces" / run_id
    if not ws.exists():
        return

    if keep_final_outputs:
        _backup_final_outputs(ws, run_id)

    shutil.rmtree(ws, ignore_errors=True)
    log.debug(f"Run workspace cleaned: {ws}")


def _backup_final_outputs(ws: Path, run_id: str) -> None:
    """Copies final deliverables to emergency_export as a safety net."""
    targets = [
        ws / "video" / "long_video.mp4",
        ws / "video" / "short_video.mp4",
        ws / "thumbnails" / "thumbnail.jpg",
    ]
    dest_dir = EMERGENCY_EXPORT_DIR / run_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    for src in targets:
        if src.exists():
            shutil.copy2(str(src), str(dest_dir / src.name))
            log.debug(f"Emergency backup: {src.name} → {dest_dir}")


# ─────────────────────────────────────────────
# JSON PERSISTENCE (story bank, analytics, heuristics)
# ─────────────────────────────────────────────

def load_json(relative_path: str, default: Any = None) -> Any:
    """
    Loads a JSON file relative to DATA_DIR.
    Returns default if file does not exist or is corrupt.
    """
    full_path = DATA_DIR / relative_path
    if not full_path.exists():
        return default if default is not None else {}
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning(f"Could not load {relative_path}: {exc}. Using default.")
        return default if default is not None else {}


def save_json(relative_path: str, data: Any, indent: int = 2) -> bool:
    """
    Saves data as JSON relative to DATA_DIR.
    Performs atomic write (write to .tmp then rename) to avoid corruption.
    Returns True on success.
    """
    full_path = DATA_DIR / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = full_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False, default=str)
        tmp_path.replace(full_path)
        return True
    except OSError as exc:
        log.error(f"Failed to save {relative_path}: {exc}")
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        return False


# ─────────────────────────────────────────────
# STORY BANK MANAGEMENT
# ─────────────────────────────────────────────

def load_story_bank(bank_key: str) -> list:
    """Loads a story bank by key (e.g. 'verified_real', 'paranormal')."""
    path = STORY_BANK_FILES.get(bank_key)
    if not path:
        log.error(f"Unknown story bank key: {bank_key}")
        return []
    return load_json(path, default=[])


def save_story_bank(bank_key: str, stories: list) -> bool:
    path = STORY_BANK_FILES.get(bank_key)
    if not path:
        return False
    return save_json(path, stories)


def get_used_story_ids() -> set:
    ids = load_json(STORY_BANK_FILES["used_ids"], default=[])
    return set(ids)


def mark_story_used(story_id: str) -> None:
    used = list(get_used_story_ids())
    if story_id not in used:
        used.append(story_id)
        save_json(STORY_BANK_FILES["used_ids"], used)


def story_id_from_content(title: str, source: str) -> str:
    """Generates a stable deterministic ID from story title + source."""
    raw = f"{title.lower().strip()}::{source.lower().strip()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


# ─────────────────────────────────────────────
# PUBLICATION LOG
# ─────────────────────────────────────────────

def load_publication_log() -> list:
    return load_json(PUBLICATION_LOG_FILE, default=[])


def append_publication_log(entry: dict) -> None:
    log_data = load_publication_log()
    entry["logged_at"] = datetime.now(timezone.utc).isoformat()
    log_data.append(entry)
    # Keep last 500 entries only — GHA disk space awareness
    if len(log_data) > 500:
        log_data = log_data[-500:]
    save_json(PUBLICATION_LOG_FILE, log_data)


# ─────────────────────────────────────────────
# HEURISTICS (adaptive self-learning weights)
# ─────────────────────────────────────────────

def load_heuristics() -> dict:
    data = load_json(HEURISTICS_FILE, default=None)
    if data is None:
        log.info("No heuristics file found — initializing with defaults.")
        save_json(HEURISTICS_FILE, HEURISTICS_DEFAULT)
        return dict(HEURISTICS_DEFAULT)
    # Merge in any new keys from defaults that don't exist yet
    merged = dict(HEURISTICS_DEFAULT)
    merged.update(data)
    return merged


def save_heuristics(heuristics: dict) -> None:
    heuristics["last_updated"] = datetime.now(timezone.utc).isoformat()
    save_json(HEURISTICS_FILE, heuristics)


# ─────────────────────────────────────────────
# RUN ID GENERATION
# ─────────────────────────────────────────────

def generate_run_id() -> str:
    """
    Generates a short, unique, sortable run ID.
    Format: YYYYMMDD_HHMMSS_<4 hex chars>
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]


# ─────────────────────────────────────────────
# ASSET PATH HELPERS
# ─────────────────────────────────────────────

def audio_path(run_id: str, filename: str) -> Path:
    return WORKSPACE_DIR / "run_workspaces" / run_id / "audio" / filename


def image_path(run_id: str, filename: str) -> Path:
    return WORKSPACE_DIR / "run_workspaces" / run_id / "images" / filename


def video_path(run_id: str, filename: str) -> Path:
    return WORKSPACE_DIR / "run_workspaces" / run_id / "video" / filename


def thumbnail_path(run_id: str, filename: str = "thumbnail.jpg") -> Path:
    return WORKSPACE_DIR / "run_workspaces" / run_id / "thumbnails" / filename


def card_path(run_id: str, filename: str) -> Path:
    return WORKSPACE_DIR / "run_workspaces" / run_id / "cards" / filename


# ─────────────────────────────────────────────
# EMERGENCY EXPORT (upload failure safety net)
# ─────────────────────────────────────────────

def emergency_export(
    run_id: str,
    long_mp4: Optional[Path],
    short_mp4: Optional[Path],
    thumbnail: Optional[Path],
    metadata: dict,
) -> Path:
    """
    Called when YouTube upload fails across all credential packs.
    Saves all deliverables to EMERGENCY_EXPORT_DIR so no content is lost.
    Returns the export directory path.
    """
    dest_dir = EMERGENCY_EXPORT_DIR / run_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    for src, name in [
        (long_mp4,   "long_video.mp4"),
        (short_mp4,  "short_video.mp4"),
        (thumbnail,  "thumbnail.jpg"),
    ]:
        if src and Path(src).exists():
            shutil.copy2(str(src), str(dest_dir / name))
            log.info(f"Emergency export saved: {name}")

    meta_path = dest_dir / "metadata.json"
    metadata["emergency_export_at"] = datetime.now(timezone.utc).isoformat()
    metadata["run_id"] = run_id
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False, default=str)

    log.warning(f"EMERGENCY EXPORT complete → {dest_dir}")
    return dest_dir


# ─────────────────────────────────────────────
# FONT RESOLUTION (CI-safe)
# ─────────────────────────────────────────────

def resolve_font(preferred: str, fallback: str = "DejaVu Sans Bold") -> str:
    """
    Returns a font name or path that FFmpeg/Pillow can use on GHA runner.
    Falls back to system DejaVu if preferred font is unavailable.
    """
    # Check local assets/fonts directory first
    from config.settings import FONTS_DIR
    for ext in [".ttf", ".otf"]:
        candidate = FONTS_DIR / f"{preferred}{ext}"
        if candidate.exists():
            return str(candidate)

    # Check system font paths (Ubuntu GHA runner)
    system_paths = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf"),
    ]
    for p in system_paths:
        if p.exists():
            return str(p)

    return fallback
