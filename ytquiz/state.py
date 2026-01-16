from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ytquiz.utils import UTC, ensure_dir, json_dumps, json_loads


@dataclass(frozen=True)
class VideoRecord:
    video_id: str
    kind: str
    title: str
    description: str
    scheduled_at: str
    published_at: str
    template_id: int
    topic_id: str
    question_text: str
    answer_text: str
    question_hash: str
    voice_gender: str
    countdown_seconds: int
    video_length_seconds: float
    music_mode: str
    bg_source: str
    features_json: str
    metrics_json: str | None
    score: float | None
    metrics_updated_at: str | None


class StateDB:
    def __init__(self, db_path: Path) -> None:
        ensure_dir(db_path.parent)
        self._path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def _migrate(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kv (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              video_id TEXT UNIQUE NOT NULL,
              kind TEXT NOT NULL,
              title TEXT NOT NULL,
              description TEXT NOT NULL,
              scheduled_at TEXT NOT NULL,
              published_at TEXT NOT NULL,
              template_id INTEGER NOT NULL,
              topic_id TEXT NOT NULL,
              question_text TEXT NOT NULL,
              answer_text TEXT NOT NULL,
              question_hash TEXT NOT NULL,
              voice_gender TEXT NOT NULL,
              countdown_seconds INTEGER NOT NULL,
              video_length_seconds REAL NOT NULL,
              music_mode TEXT NOT NULL,
              bg_source TEXT NOT NULL,
              features_json TEXT NOT NULL,
              metrics_json TEXT,
              score REAL,
              metrics_updated_at TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_videos_kind ON videos(kind)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_videos_published ON videos(published_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_videos_qhash ON videos(question_hash)")
        self._conn.commit()

    def get_kv(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json_loads(row["value"])
        except Exception:
            return default

    def set_kv(self, key: str, value: Any) -> None:
        s = json_dumps(value)
        self._conn.execute(
            "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, s),
        )
        self._conn.commit()

    def total_videos(self) -> int:
        row = self._conn.execute("SELECT COUNT(1) AS c FROM videos").fetchone()
        return int(row["c"] or 0)

    def video_count(self) -> int:
        return self.total_videos()

    def exists_question_hash(self, qhash: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM videos WHERE question_hash=? LIMIT 1", (qhash,)).fetchone()
        return row is not None

    def recent_questions(self, limit: int = 300) -> list[str]:
        rows = self._conn.execute(
            "SELECT question_text FROM videos ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [str(r["question_text"]) for r in rows]

    def answers_recently_used(self, answer: str, days: int = 30) -> int:
        since = (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
        row = self.conn.execute(
            "SELECT COUNT(1) AS c FROM videos WHERE published_at>=? AND answer_text=?",
            (since, answer),
        ).fetchone()
        return int(row["c"] or 0)

    def select_compilation_short_items(self, *, limit: int, max_days: int = 90) -> list[sqlite3.Row]:
        cutoff = (datetime.now(tz=UTC) - timedelta(days=max_days)).isoformat()
        scored = self.conn.execute(
            """
            SELECT * FROM videos
            WHERE kind='short' AND published_at>=? AND score IS NOT NULL
            ORDER BY score DESC, id DESC
            LIMIT ?
            """,
            (cutoff, int(limit)),
        ).fetchall()

        if len(scored) >= limit:
            return list(scored)

        chosen_ids: set[int] = {int(r["id"]) for r in scored}
        remaining = int(limit) - len(scored)

        recent = self.conn.execute(
            """
            SELECT * FROM videos
            WHERE kind='short' AND published_at>=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (cutoff, int(limit) * 3),
        ).fetchall()

        out = list(scored)
        for r in recent:
            rid = int(r["id"])
            if rid in chosen_ids:
                continue
            out.append(r)
            chosen_ids.add(rid)
            if len(out) >= limit:
                break

        return out[:limit]

    def insert_video(
        self,
        *,
        video_id: str,
        kind: str,
        title: str,
        description: str,
        scheduled_at: str,
        published_at: str,
        template_id: int,
        topic_id: str,
        question_text: str,
        answer_text: str,
        question_hash: str,
        voice_gender: str,
        countdown_seconds: int,
        video_length_seconds: float,
        music_mode: str,
        bg_source: str,
        features: dict[str, Any],
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO videos(
              video_id,kind,title,description,scheduled_at,published_at,template_id,topic_id,
              question_text,answer_text,question_hash,voice_gender,countdown_seconds,video_length_seconds,
              music_mode,bg_source,features_json,metrics_json,score,metrics_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                video_id,
                kind,
                title,
                description,
                scheduled_at,
                published_at,
                int(template_id),
                topic_id,
                question_text,
                answer_text,
                question_hash,
                voice_gender,
                int(countdown_seconds),
                float(video_length_seconds),
                music_mode,
                bg_source,
                json_dumps(features),
                None,
                None,
                None,
            ),
        )
        self._conn.commit()

    def update_metrics(self, *, video_id: str, metrics: dict[str, Any], score: float | None) -> None:
        self._conn.execute(
            "UPDATE videos SET metrics_json=?, score=?, metrics_updated_at=? WHERE video_id=?",
            (
                json_dumps(metrics),
                score,
                datetime.now(tz=UTC).isoformat(),
                video_id,
            ),
        )
        self._conn.commit()

    def list_videos_needing_metrics(
        self,
        *,
        min_age_hours: int = 24,
        max_days: int = 30,
        update_every_hours: int = 24,
        limit: int = 40,
    ) -> list[sqlite3.Row]:
        now = datetime.now(tz=UTC)
        min_age = now - timedelta(hours=min_age_hours)
        max_age = now - timedelta(days=max_days)
        update_before = now - timedelta(hours=update_every_hours)

        rows = self._conn.execute(
            """
            SELECT * FROM videos
            WHERE published_at<=?
              AND published_at>=?
              AND (metrics_updated_at IS NULL OR metrics_updated_at<=?)
            ORDER BY published_at DESC
            LIMIT ?
            """,
            (min_age.isoformat(), max_age.isoformat(), update_before.isoformat(), int(limit)),
        ).fetchall()
        return rows

    def list_scored_videos(self, days: int = 180) -> list[sqlite3.Row]:
        cutoff = (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
        return self._conn.execute(
            "SELECT * FROM videos WHERE score IS NOT NULL AND published_at>=? ORDER BY id DESC",
            (cutoff,),
        ).fetchall()

    def list_recent_videos(self, days: int = 30) -> list[sqlite3.Row]:
        cutoff = (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
        return self._conn.execute("SELECT * FROM videos WHERE published_at>=? ORDER BY id DESC", (cutoff,)).fetchall()
