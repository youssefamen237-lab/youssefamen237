"""
database/db.py
==============
SQLite connection manager and all CRUD helper functions for the
MindCraft Psychology pipeline.

Usage
-----
    from database.db import Database

    db = Database()                 # uses DB_PATH from settings.py
    db.init()                       # creates tables + indexes if not present

    # Save a generated script
    script_id = db.insert_script(
        hook="If someone does this while talking...",
        body="It means their brain is activating the mirror neuron system.",
        cta="Follow for daily psychology secrets",
        title="Mirror Neurons Explained #psychologyfacts",
        description="...",
        tags=["psychology", "mirror neurons"],
        topic="social cognition",
        source_trend="mirror neurons",
        llm_provider="gemini",
    )

    # Check before inserting
    if not db.script_exists(hook, body):
        script_id = db.insert_script(...)

Architecture
------------
- Thread-safe via per-call connections (check_same_thread=False +
  WAL mode for concurrent reads from GitHub Actions jobs).
- All timestamps are UTC ISO-8601 strings.
- UUIDs are generated in Python (uuid.uuid4) for portability.
"""

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

from config.settings import DB_PATH
from database.models import ALL_CREATE_STATEMENTS, ALL_INDEX_STATEMENTS
from utils.logger import get_logger

logger = get_logger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────

def _now_utc() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _make_id() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


def _content_hash(hook: str, body: str) -> str:
    """
    Compute a SHA-256 fingerprint of the hook + body text.
    Used as the deduplication key in the scripts table.
    Normalise whitespace and lower-case before hashing so
    near-duplicates with different spacing are still caught.
    """
    normalised = f"{hook.strip().lower()}||{body.strip().lower()}"
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


# ── Database class ─────────────────────────────────────────────────────────

class Database:
    """
    Thin wrapper around SQLite providing:
    - Auto-initialisation of schema on first use.
    - Context-manager connection handling (WAL mode, foreign keys on).
    - Typed insert / query methods for each pipeline stage.
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Connection ──────────────────────────────────────────────────────────

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Yield an open SQLite connection configured for production use:
        - WAL journal mode — allows concurrent reads while writing.
        - Foreign key enforcement.
        - Row factory so rows behave like dicts.
        """
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Schema initialisation ───────────────────────────────────────────────

    def init(self) -> None:
        """
        Create all tables and indexes if they do not already exist.
        Safe to call on every startup — uses IF NOT EXISTS guards.
        """
        logger.info("Initialising database at %s", self.db_path)
        with self._connect() as conn:
            for stmt in ALL_CREATE_STATEMENTS:
                conn.execute(stmt)
            for stmt in ALL_INDEX_STATEMENTS:
                conn.execute(stmt)
        logger.info("Database ready.")

    # ══════════════════════════════════════════════════════════════════════
    # SCRIPTS
    # ══════════════════════════════════════════════════════════════════════

    def script_exists(self, hook: str, body: str) -> bool:
        """
        Return True if a script with the same hook+body content hash
        already exists in the database (regardless of status).
        Call this BEFORE generating TTS/visuals to avoid wasted API calls.
        """
        h = _content_hash(hook, body)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM scripts WHERE content_hash = ?", (h,)
            ).fetchone()
        return row is not None

    def insert_script(
        self,
        hook: str,
        body: str,
        cta: str,
        title: str,
        description: str,
        tags: list[str],
        topic: str,
        source_trend: Optional[str] = None,
        llm_provider: str = "gemini",
    ) -> str:
        """
        Persist a new script. Returns the new UUID.
        Raises ValueError if a duplicate content hash exists.
        """
        content_hash = _content_hash(hook, body)
        if self.script_exists(hook, body):
            raise ValueError(
                f"Duplicate script detected (hash={content_hash[:12]}…). "
                "Skipping insert."
            )

        script_id = _make_id()
        now = _now_utc()
        tags_json = json.dumps(tags)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scripts
                    (id, hook, body, cta, title, description, tags, topic,
                     content_hash, source_trend, llm_provider, status,
                     created_at, updated_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    script_id, hook, body, cta, title, description,
                    tags_json, topic, content_hash, source_trend,
                    llm_provider, now, now,
                ),
            )

        logger.info("Script inserted: id=%s topic='%s'", script_id, topic)
        return script_id

    def get_script(self, script_id: str) -> Optional[dict]:
        """Fetch a script row by UUID. Returns None if not found."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM scripts WHERE id = ?", (script_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["tags"] = json.loads(result["tags"])
        return result

    def mark_script_used(self, script_id: str) -> None:
        """Update status → 'used' after a video has been rendered."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE scripts SET status='used', updated_at=? WHERE id=?",
                (_now_utc(), script_id),
            )

    def mark_script_rejected(self, script_id: str, reason: str = "") -> None:
        """Mark a script as rejected (e.g., TTS or rendering failure)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE scripts SET status='rejected', updated_at=? WHERE id=?",
                (_now_utc(), script_id),
            )
        logger.warning("Script %s rejected: %s", script_id, reason)

    def get_pending_scripts(self, limit: int = 10) -> list[dict]:
        """Return pending scripts ordered oldest-first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scripts WHERE status='pending' "
                "ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        results = [dict(r) for r in rows]
        for r in results:
            r["tags"] = json.loads(r["tags"])
        return results

    # ══════════════════════════════════════════════════════════════════════
    # VIDEOS
    # ══════════════════════════════════════════════════════════════════════

    def insert_video(
        self,
        script_id: str,
        video_type: str,
        file_path: str,
        file_size_bytes: Optional[int] = None,
        duration_secs: Optional[float] = None,
        resolution: str = "1080x1920",
    ) -> str:
        """
        Record a rendered video file. Returns the new UUID.
        video_type must be 'short' or 'compilation'.
        """
        assert video_type in ("short", "compilation"), \
            f"Invalid video_type '{video_type}'"

        video_id = _make_id()
        now = _now_utc()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO videos
                    (id, script_id, video_type, file_path, file_size_bytes,
                     duration_secs, resolution, status, created_at, updated_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, 'rendered', ?, ?)
                """,
                (
                    video_id, script_id, video_type, str(file_path),
                    file_size_bytes, duration_secs, resolution, now, now,
                ),
            )

        logger.info(
            "Video recorded: id=%s type=%s path=%s",
            video_id, video_type, file_path,
        )
        return video_id

    def get_video(self, video_id: str) -> Optional[dict]:
        """Fetch a video row by UUID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM videos WHERE id = ?", (video_id,)
            ).fetchone()
        return dict(row) if row else None

    def mark_video_uploaded(self, video_id: str) -> None:
        """Update video status → 'uploaded' after a successful YT upload."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE videos SET status='uploaded', updated_at=? WHERE id=?",
                (_now_utc(), video_id),
            )

    def mark_video_failed(self, video_id: str, error: str) -> None:
        """Record a rendering or upload failure on the video row."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE videos SET status='failed', error_message=?, "
                "updated_at=? WHERE id=?",
                (error, _now_utc(), video_id),
            )

    def get_rendered_shorts(self, limit: int = 28) -> list[dict]:
        """
        Return rendered (not yet uploaded) Short videos, oldest-first.
        Used by the weekly compiler to assemble compilation clips.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM videos WHERE video_type='short' "
                "AND status='rendered' ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════════════════════════
    # UPLOADS
    # ══════════════════════════════════════════════════════════════════════

    def insert_upload(
        self,
        video_id: str,
        title: str,
        yt_client_index: int,
        youtube_video_id: Optional[str] = None,
        youtube_url: Optional[str] = None,
        privacy_status: str = "public",
        upload_status: str = "success",
        http_status_code: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> str:
        """Record the outcome of a YouTube upload attempt. Returns new UUID."""
        upload_id = _make_id()
        now = _now_utc()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO uploads
                    (id, video_id, youtube_video_id, youtube_url, title,
                     yt_client_index, privacy_status, upload_status,
                     http_status_code, error_message, uploaded_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    upload_id, video_id, youtube_video_id, youtube_url,
                    title, yt_client_index, privacy_status, upload_status,
                    http_status_code, error_message, now,
                ),
            )

        logger.info(
            "Upload recorded: status=%s yt_id=%s client=%s",
            upload_status, youtube_video_id, yt_client_index,
        )
        return upload_id

    def get_uploads_today(self, yt_client_index: int) -> int:
        """
        Count successful uploads for a given OAuth client today (UTC).
        Used by quota_tracker.py to enforce per-client daily limits.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM uploads "
                "WHERE yt_client_index=? AND upload_status='success' "
                "AND uploaded_at LIKE ?",
                (yt_client_index, f"{today}%"),
            ).fetchone()
        return row["cnt"] if row else 0

    # ══════════════════════════════════════════════════════════════════════
    # QUOTA LOG
    # ══════════════════════════════════════════════════════════════════════

    def log_quota_usage(
        self,
        yt_client_index: int,
        units_used: int,
        units_limit: int = 10_000,
    ) -> None:
        """
        Upsert today's quota usage for a given OAuth client.
        Adds units_used to any already-logged value for today.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now = _now_utc()
        row_id = _make_id()

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, units_used FROM quota_log "
                "WHERE log_date=? AND yt_client_index=?",
                (today, yt_client_index),
            ).fetchone()

            if existing:
                new_total = existing["units_used"] + units_used
                conn.execute(
                    "UPDATE quota_log SET units_used=?, updated_at=? "
                    "WHERE id=?",
                    (new_total, now, existing["id"]),
                )
                logger.debug(
                    "Quota updated: client=%s date=%s total_units=%s",
                    yt_client_index, today, new_total,
                )
            else:
                conn.execute(
                    "INSERT INTO quota_log "
                    "(id, log_date, yt_client_index, units_used, "
                    " units_limit, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (row_id, today, yt_client_index, units_used,
                     units_limit, now, now),
                )
                logger.debug(
                    "Quota row created: client=%s date=%s units=%s",
                    yt_client_index, today, units_used,
                )

    def get_quota_today(self, yt_client_index: int) -> dict:
        """
        Return today's quota row for a client.
        If no row exists yet returns {'units_used': 0, 'units_limit': 10000}.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT units_used, units_limit FROM quota_log "
                "WHERE log_date=? AND yt_client_index=?",
                (today, yt_client_index),
            ).fetchone()
        if row:
            return {"units_used": row["units_used"], "units_limit": row["units_limit"]}
        return {"units_used": 0, "units_limit": 10_000}

    def is_quota_safe(self, yt_client_index: int, units_needed: int = 1600) -> bool:
        """
        Return True if the client has enough remaining quota for one upload.
        A standard YouTube video insert costs ~1600 units.
        """
        q = self.get_quota_today(yt_client_index)
        remaining = q["units_limit"] - q["units_used"]
        safe = remaining >= units_needed
        if not safe:
            logger.warning(
                "Quota check FAILED: client=%s remaining=%s needed=%s",
                yt_client_index, remaining, units_needed,
            )
        return safe

    # ══════════════════════════════════════════════════════════════════════
    # DIAGNOSTICS
    # ══════════════════════════════════════════════════════════════════════

    def stats(self) -> dict:
        """
        Return a summary dict of current pipeline health.
        Useful for logging at the start of each GitHub Actions run.
        """
        with self._connect() as conn:
            scripts_total   = conn.execute("SELECT COUNT(*) FROM scripts").fetchone()[0]
            scripts_pending = conn.execute(
                "SELECT COUNT(*) FROM scripts WHERE status='pending'"
            ).fetchone()[0]
            scripts_used    = conn.execute(
                "SELECT COUNT(*) FROM scripts WHERE status='used'"
            ).fetchone()[0]
            videos_rendered = conn.execute(
                "SELECT COUNT(*) FROM videos WHERE status='rendered'"
            ).fetchone()[0]
            uploads_today   = conn.execute(
                "SELECT COUNT(*) FROM uploads WHERE "
                "upload_status='success' AND uploaded_at LIKE ?",
                (datetime.now(timezone.utc).strftime("%Y-%m-%d") + "%",),
            ).fetchone()[0]

        return {
            "scripts_total":   scripts_total,
            "scripts_pending": scripts_pending,
            "scripts_used":    scripts_used,
            "videos_rendered": videos_rendered,
            "uploads_today":   uploads_today,
        }
