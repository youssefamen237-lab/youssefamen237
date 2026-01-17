from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytz


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS run_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS duplicates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL, -- question|answer|title
    norm_text TEXT NOT NULL,
    hash TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_duplicates_kind_hash ON duplicates(kind, hash);
CREATE INDEX IF NOT EXISTS idx_duplicates_kind_norm ON duplicates(kind, norm_text);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT,
    kind TEXT NOT NULL, -- short|long
    publish_at_utc TEXT NOT NULL,
    template_id TEXT,
    topic TEXT,
    difficulty TEXT,
    countdown_seconds INTEGER,
    voice_gender TEXT,
    music_track_id TEXT,
    bg_image_id TEXT,
    title_style_id TEXT,
    title TEXT,
    description TEXT,
    tags_csv TEXT,
    question TEXT,
    answer TEXT,
    extra_json TEXT,
    created_at_utc TEXT NOT NULL,
    uploaded_at_utc TEXT,
    status TEXT NOT NULL, -- planned|rendered|uploaded|failed
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_videos_publish_kind ON videos(kind, publish_at_utc);
"""


def utc_now_iso() -> str:
    return datetime.now(tz=pytz.UTC).isoformat()


class DB:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # --- state ---
    def get_state(self, key: str) -> Optional[str]:
        cur = self._conn.execute("SELECT value FROM run_state WHERE key=?", (key,))
        row = cur.fetchone()
        return None if row is None else str(row["value"])

    def set_state(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO run_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    # --- duplicates ---
    def add_duplicate(self, kind: str, norm_text: str, h: str) -> None:
        self._conn.execute(
            "INSERT INTO duplicates(kind,norm_text,hash,created_at_utc) VALUES(?,?,?,?)",
            (kind, norm_text, h, utc_now_iso()),
        )
        self._conn.commit()

    def seen_hash(self, kind: str, h: str) -> bool:
        cur = self._conn.execute("SELECT 1 FROM duplicates WHERE kind=? AND hash=? LIMIT 1", (kind, h))
        return cur.fetchone() is not None

    def recent_norm_texts(self, kind: str, days: int = 180, limit: int = 2000) -> List[str]:
        cutoff = datetime.now(tz=pytz.UTC) - timedelta(days=days)
        cur = self._conn.execute(
            "SELECT norm_text, created_at_utc FROM duplicates WHERE kind=? ORDER BY id DESC LIMIT ?",
            (kind, int(limit)),
        )
        out: List[str] = []
        for row in cur.fetchall():
            try:
                ts = datetime.fromisoformat(row["created_at_utc"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=pytz.UTC)
            except Exception:
                continue
            if ts >= cutoff:
                out.append(str(row["norm_text"]))
            else:
                # newest-first; stop once older than cutoff
                break
        return out

    # --- videos ---
    def insert_video_plan(self, record: Dict[str, Any]) -> int:
        keys = list(record.keys())
        cols = ",".join(keys)
        qs = ",".join(["?"] * len(keys))
        values = [record[k] for k in keys]
        cur = self._conn.execute(f"INSERT INTO videos({cols}) VALUES({qs})", values)
        self._conn.commit()
        return int(cur.lastrowid)

    def update_video(self, row_id: int, **fields: Any) -> None:
        if not fields:
            return
        keys = list(fields.keys())
        sets = ",".join([f"{k}=?" for k in keys])
        values = [fields[k] for k in keys]
        values.append(row_id)
        self._conn.execute(f"UPDATE videos SET {sets} WHERE id=?", values)
        self._conn.commit()

    def list_unuploaded_for_dateprefix(self, date_utc_prefix: str) -> List[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM videos WHERE publish_at_utc LIKE ? AND status IN ('planned','rendered') ORDER BY publish_at_utc",
            (f"{date_utc_prefix}%",),
        )
        return list(cur.fetchall())

    def list_pending_between(self, start_utc_iso: str, end_utc_iso: str) -> list[sqlite3.Row]:
        """List planned/rendered videos scheduled within [start_utc_iso, end_utc_iso).

        NOTE: publish_at_utc is stored in UTC ISO-8601 format, so lexicographic range queries are safe.
        """
        cur = self._conn.execute(
            "SELECT * FROM videos WHERE publish_at_utc >= ? AND publish_at_utc < ? AND status IN ('planned','rendered') ORDER BY publish_at_utc",
            (start_utc_iso, end_utc_iso),
        )
        return list(cur.fetchall())

    def count_for_dateprefix(self, kind: str, date_utc_prefix: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(1) AS c FROM videos WHERE kind=? AND publish_at_utc LIKE ?",
            (kind, f"{date_utc_prefix}%"),
        )
        row = cur.fetchone()
        return int(row["c"]) if row else 0

    def list_unuploaded(self, date_utc_prefix: str) -> List[sqlite3.Row]:
        return self.list_unuploaded_for_dateprefix(date_utc_prefix)

    def planned_today(self, kind: str, date_utc_prefix: str) -> int:
        return self.count_for_dateprefix(kind, date_utc_prefix)

    def recent_texts(self, kind: str, days: int, limit: int = 2000) -> List[str]:
        return self.recent_norm_texts(kind=kind, days=days, limit=limit)

    def list_recent_videos(self, days: int = 14, limit: int = 2000) -> List[sqlite3.Row]:
        cutoff = datetime.now(tz=pytz.UTC) - timedelta(days=days)
        cur = self._conn.execute(
            "SELECT * FROM videos ORDER BY created_at_utc DESC LIMIT ?",
            (int(limit),),
        )
        out: List[sqlite3.Row] = []
        for row in cur.fetchall():
            try:
                ts = datetime.fromisoformat(row["created_at_utc"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=pytz.UTC)
            except Exception:
                continue
            if ts >= cutoff:
                out.append(row)
            else:
                break
        return out
