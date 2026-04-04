"""
utils/file_utils.py
===================
Safe file I/O helpers, temp file lifecycle management, and path
utilities used across the MindCraft Psychology pipeline.
"""

import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


# ── Directory helpers ───────────────────────────────────────────────────────

def ensure_dir(path: Path) -> Path:
    """Create `path` (and any parents) if it does not exist. Returns path."""
    Path(path).mkdir(parents=True, exist_ok=True)
    return Path(path)


def ensure_dirs(*paths) -> None:
    """Create multiple directories in one call."""
    for p in paths:
        ensure_dir(p)


# ── Safe file operations ────────────────────────────────────────────────────

def safe_delete(path: Path) -> bool:
    """
    Delete a file without raising if it does not exist or cannot be removed.
    Returns True if the file was deleted, False otherwise.
    """
    try:
        Path(path).unlink(missing_ok=True)
        logger.debug("Deleted: %s", path)
        return True
    except OSError as exc:
        logger.warning("Could not delete %s: %s", path, exc)
        return False


def safe_move(src: Path, dst: Path) -> Optional[Path]:
    """
    Move `src` to `dst`, creating parent directories as needed.
    Returns the destination path on success, None on failure.
    """
    try:
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        logger.debug("Moved: %s → %s", src, dst)
        return dst
    except OSError as exc:
        logger.error("Could not move %s → %s: %s", src, dst, exc)
        return None


def safe_copy(src: Path, dst: Path) -> Optional[Path]:
    """
    Copy `src` to `dst`. Returns destination path on success, None on failure.
    """
    try:
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        logger.debug("Copied: %s → %s", src, dst)
        return dst
    except OSError as exc:
        logger.error("Could not copy %s → %s: %s", src, dst, exc)
        return None


# ── Temp file management ────────────────────────────────────────────────────

@contextmanager
def temp_file(suffix: str = ".tmp", prefix: str = "mindcraft_") -> Generator[Path, None, None]:
    """
    Context manager that creates a named temp file and deletes it on exit.

    Usage
    -----
        with temp_file(suffix=".mp3") as tmp:
            render_audio(tmp)
            process(tmp)
        # tmp is automatically deleted here
    """
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix)
    os.close(fd)
    tmp_path = Path(path)
    try:
        yield tmp_path
    finally:
        safe_delete(tmp_path)


@contextmanager
def temp_dir(prefix: str = "mindcraft_") -> Generator[Path, None, None]:
    """
    Context manager that creates a temp directory and removes it on exit.

    Usage
    -----
        with temp_dir() as td:
            (td / "frame.png").write_bytes(data)
        # td and all contents deleted on exit
    """
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield tmp
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
            logger.debug("Removed temp dir: %s", tmp)
        except OSError as exc:
            logger.warning("Could not remove temp dir %s: %s", tmp, exc)


# ── Output directory cleanup ────────────────────────────────────────────────

def cleanup_output_dir(directory: Path, pattern: str = "*.mp4", keep: int = 20) -> int:
    """
    Delete old files from `directory` matching `pattern`, keeping the
    `keep` most-recently-modified files.

    Prevents disk exhaustion on GitHub Actions runners that accumulate
    rendered clips across workflow runs.

    Parameters
    ----------
    directory : Directory to clean.
    pattern   : Glob pattern for files to consider (e.g. '*.mp4').
    keep      : Number of most-recent files to retain.

    Returns
    -------
    Number of files deleted.
    """
    directory = Path(directory)
    if not directory.exists():
        return 0

    files = sorted(
        directory.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    to_delete = files[keep:]
    deleted = 0
    for f in to_delete:
        if safe_delete(f):
            deleted += 1

    if deleted:
        logger.info(
            "Cleanup: removed %d old file(s) from %s (kept %d)",
            deleted, directory, keep,
        )
    return deleted


def cleanup_audio_files(audio_dir: Path, keep: int = 10) -> int:
    """Remove old .mp3 TTS files, keeping the most recent `keep`."""
    return cleanup_output_dir(audio_dir, pattern="*.mp3", keep=keep)


def cleanup_clip_files(clips_dir: Path, keep: int = 15) -> int:
    """Remove old downloaded stock clips to free disk space."""
    return cleanup_output_dir(clips_dir, pattern="*.mp4", keep=keep)


# ── File info helpers ───────────────────────────────────────────────────────

def file_size_mb(path: Path) -> float:
    """Return file size in megabytes, or 0.0 if the file does not exist."""
    try:
        return Path(path).stat().st_size / 1_048_576
    except OSError:
        return 0.0


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    """
    Return a path guaranteed not to exist in `directory`.
    Appends a short UUID fragment if the plain name is taken.

    Parameters
    ----------
    directory : Target directory.
    stem      : Base filename without extension.
    suffix    : File extension including dot (e.g. '.mp4').

    Returns
    -------
    Path object that does not yet exist on disk.
    """
    candidate = Path(directory) / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    short_uid = str(uuid.uuid4())[:8]
    return Path(directory) / f"{stem}_{short_uid}{suffix}"


def read_text_safe(path: Path, encoding: str = "utf-8") -> Optional[str]:
    """Read a text file and return its contents, or None on error."""
    try:
        return Path(path).read_text(encoding=encoding)
    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return None


def write_text_safe(path: Path, content: str, encoding: str = "utf-8") -> bool:
    """Write `content` to `path`, creating parent dirs. Returns True on success."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return True
    except OSError as exc:
        logger.error("Could not write %s: %s", path, exc)
        return False
