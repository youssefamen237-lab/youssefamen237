"""
database/models.py
==================
SQLite table definitions for the MindCraft Psychology pipeline.

Tables
------
scripts     — every generated script (hook + body + metadata).
              A SHA-256 hash of hook+body prevents re-use.
videos      — every rendered Short or compilation video file.
uploads     — every successful YouTube upload with video ID.
quota_log   — daily YouTube API unit consumption per OAuth client.

Design notes
------------
- All primary keys are TEXT UUIDs (generated in Python, not SQLite).
  This keeps IDs portable across potential future DB migrations.
- created_at / updated_at are stored as ISO-8601 UTC strings for
  SQLite compatibility (SQLite has no native DATETIME type).
- status columns use short string codes instead of integers so
  the DB is human-readable without a lookup table.
"""

# ── Table creation SQL ─────────────────────────────────────────────────────

CREATE_SCRIPTS_TABLE: str = """
CREATE TABLE IF NOT EXISTS scripts (
    id              TEXT    PRIMARY KEY,          -- UUID4
    hook            TEXT    NOT NULL,             -- Frame 1 text
    body            TEXT    NOT NULL,             -- Frame 2 text
    cta             TEXT    NOT NULL,             -- Frame 3 text (usually fixed)
    title           TEXT    NOT NULL,             -- YouTube title
    description     TEXT    NOT NULL,             -- YouTube description
    tags            TEXT    NOT NULL,             -- JSON array serialised as string
    topic           TEXT    NOT NULL,             -- broad psychology topic
    content_hash    TEXT    NOT NULL UNIQUE,      -- SHA-256(hook + body) — dedup key
    source_trend    TEXT,                         -- Tavily trend keyword that inspired this
    llm_provider    TEXT    NOT NULL DEFAULT 'gemini',  -- 'gemini' | 'groq'
    status          TEXT    NOT NULL DEFAULT 'pending', -- 'pending' | 'used' | 'rejected'
    created_at      TEXT    NOT NULL,             -- ISO-8601 UTC
    updated_at      TEXT    NOT NULL              -- ISO-8601 UTC
);
"""

CREATE_SCRIPTS_INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_scripts_status       ON scripts (status);",
    "CREATE INDEX IF NOT EXISTS idx_scripts_content_hash ON scripts (content_hash);",
    "CREATE INDEX IF NOT EXISTS idx_scripts_created_at   ON scripts (created_at);",
]

# ─────────────────────────────────────────────────────────────────────────────

CREATE_VIDEOS_TABLE: str = """
CREATE TABLE IF NOT EXISTS videos (
    id              TEXT    PRIMARY KEY,          -- UUID4
    script_id       TEXT    NOT NULL,             -- FK → scripts.id
    video_type      TEXT    NOT NULL,             -- 'short' | 'compilation'
    file_path       TEXT    NOT NULL,             -- absolute path to .mp4
    file_size_bytes INTEGER,                      -- size on disk
    duration_secs   REAL,                         -- rendered duration in seconds
    resolution      TEXT,                         -- e.g. '1080x1920'
    status          TEXT    NOT NULL DEFAULT 'rendered',
                                                  -- 'rendered' | 'uploaded' | 'failed'
    error_message   TEXT,                         -- populated if status = 'failed'
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    FOREIGN KEY (script_id) REFERENCES scripts (id)
);
"""

CREATE_VIDEOS_INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_videos_script_id  ON videos (script_id);",
    "CREATE INDEX IF NOT EXISTS idx_videos_status     ON videos (status);",
    "CREATE INDEX IF NOT EXISTS idx_videos_video_type ON videos (video_type);",
]

# ─────────────────────────────────────────────────────────────────────────────

CREATE_UPLOADS_TABLE: str = """
CREATE TABLE IF NOT EXISTS uploads (
    id                  TEXT    PRIMARY KEY,      -- UUID4
    video_id            TEXT    NOT NULL,         -- FK → videos.id
    youtube_video_id    TEXT    UNIQUE,           -- YouTube's assigned video ID
    youtube_url         TEXT,                     -- full watch URL
    title               TEXT    NOT NULL,
    yt_client_index     INTEGER NOT NULL,         -- 1 | 2 | 3 (which OAuth client was used)
    privacy_status      TEXT    NOT NULL DEFAULT 'public',
                                                  -- 'public' | 'unlisted' | 'private'
    upload_status       TEXT    NOT NULL DEFAULT 'success',
                                                  -- 'success' | 'failed' | 'quota_exceeded'
    http_status_code    INTEGER,                  -- HTTP response code from YT API
    error_message       TEXT,
    uploaded_at         TEXT    NOT NULL,         -- ISO-8601 UTC
    FOREIGN KEY (video_id) REFERENCES videos (id)
);
"""

CREATE_UPLOADS_INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_uploads_video_id         ON uploads (video_id);",
    "CREATE INDEX IF NOT EXISTS idx_uploads_youtube_video_id ON uploads (youtube_video_id);",
    "CREATE INDEX IF NOT EXISTS idx_uploads_uploaded_at      ON uploads (uploaded_at);",
    "CREATE INDEX IF NOT EXISTS idx_uploads_yt_client_index  ON uploads (yt_client_index);",
]

# ─────────────────────────────────────────────────────────────────────────────

CREATE_QUOTA_LOG_TABLE: str = """
CREATE TABLE IF NOT EXISTS quota_log (
    id              TEXT    PRIMARY KEY,          -- UUID4
    log_date        TEXT    NOT NULL,             -- ISO date: 'YYYY-MM-DD'
    yt_client_index INTEGER NOT NULL,             -- 1 | 2 | 3
    units_used      INTEGER NOT NULL DEFAULT 0,   -- YouTube API units consumed
    units_limit     INTEGER NOT NULL DEFAULT 10000,-- free-tier daily limit
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    UNIQUE (log_date, yt_client_index)            -- one row per client per day
);
"""

CREATE_QUOTA_LOG_INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_quota_log_date ON quota_log (log_date);",
]

# ─────────────────────────────────────────────────────────────────────────────
# Convenience collections used by db.py to initialise all tables at once

ALL_CREATE_STATEMENTS: list[str] = [
    CREATE_SCRIPTS_TABLE,
    CREATE_VIDEOS_TABLE,
    CREATE_UPLOADS_TABLE,
    CREATE_QUOTA_LOG_TABLE,
]

ALL_INDEX_STATEMENTS: list[str] = (
    CREATE_SCRIPTS_INDEXES
    + CREATE_VIDEOS_INDEXES
    + CREATE_UPLOADS_INDEXES
    + CREATE_QUOTA_LOG_INDEXES
)
