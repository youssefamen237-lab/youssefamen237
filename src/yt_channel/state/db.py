from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class ProviderHealth:
    provider_key: str
    fail_count: int
    cooldown_until: Optional[str]
    last_error: Optional[str]


class StateDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        _ensure_parent(db_path)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def _init_schema(self) -> None:
        c = self.conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                video_id TEXT,
                publish_at TEXT,
                created_at TEXT NOT NULL,
                uploaded_at TEXT,
                status TEXT NOT NULL,

                template_id TEXT,
                topic TEXT,
                difficulty INTEGER,
                countdown_seconds INTEGER,
                voice_gender TEXT,
                music_track_id TEXT,
                bg_image_id TEXT,
                title_style_id TEXT,

                question_id TEXT,
                question_text TEXT,
                answer_text TEXT,

                title TEXT,
                description TEXT,
                tags_json TEXT,
                metadata_json TEXT,
                metrics_json TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS dedupe_hashes (
                hash TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS answer_cooldown (
                answer_hash TEXT PRIMARY KEY,
                last_used_at TEXT NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_health (
                provider_key TEXT PRIMARY KEY,
                fail_count INTEGER NOT NULL,
                cooldown_until TEXT,
                last_error TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS bandit_arms (
                arm_type TEXT NOT NULL,
                arm_value TEXT NOT NULL,
                alpha REAL NOT NULL,
                beta REAL NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (arm_type, arm_value)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS run_reports (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                report_json TEXT
            )
            """
        )
        self.conn.commit()

    # ------------------ Dedupe ------------------
    def has_hash(self, kind: str, h: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM dedupe_hashes WHERE hash=? LIMIT 1", (h,))
        return cur.fetchone() is not None

    def add_hash(self, kind: str, h: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO dedupe_hashes(hash, kind, created_at) VALUES(?,?,?)",
            (h, kind, _utc_now_iso()),
        )
        self.conn.commit()

    def answer_in_cooldown(self, answer_hash: str, cooldown_days: int) -> bool:
        cur = self.conn.execute("SELECT last_used_at FROM answer_cooldown WHERE answer_hash=?", (answer_hash,))
        row = cur.fetchone()
        if not row:
            return False
        try:
            last = datetime.fromisoformat(row["last_used_at"])
        except Exception:
            return False
        return datetime.now(timezone.utc) - last < timedelta(days=cooldown_days)

    def touch_answer(self, answer_hash: str) -> None:
        self.conn.execute(
            "INSERT INTO answer_cooldown(answer_hash, last_used_at) VALUES(?,?) "
            "ON CONFLICT(answer_hash) DO UPDATE SET last_used_at=excluded.last_used_at",
            (answer_hash, _utc_now_iso()),
        )
        self.conn.commit()

    # ------------------ Video records ------------------
    def insert_video_planned(
        self,
        *,
        kind: str,
        publish_at: Optional[str],
        template_id: str,
        topic: str,
        difficulty: int,
        countdown_seconds: int,
        voice_gender: str,
        music_track_id: Optional[str],
        bg_image_id: Optional[str],
        title_style_id: str,
        question_id: str,
        question_text: str,
        answer_text: str,
        title: str,
        description: str,
        tags: List[str],
        metadata: Dict[str, Any],
    ) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO videos(
                kind, video_id, publish_at, created_at, uploaded_at, status,
                template_id, topic, difficulty, countdown_seconds, voice_gender,
                music_track_id, bg_image_id, title_style_id,
                question_id, question_text, answer_text,
                title, description, tags_json, metadata_json, metrics_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                kind,
                None,
                publish_at,
                _utc_now_iso(),
                None,
                "planned",
                template_id,
                topic,
                difficulty,
                countdown_seconds,
                voice_gender,
                music_track_id,
                bg_image_id,
                title_style_id,
                question_id,
                question_text,
                answer_text,
                title,
                description,
                json.dumps(tags, ensure_ascii=False),
                json.dumps(metadata, ensure_ascii=False),
                None,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def mark_video_uploaded(self, row_id: int, *, video_id: str, status: str = "uploaded") -> None:
        self.conn.execute(
            "UPDATE videos SET video_id=?, uploaded_at=?, status=? WHERE id=?",
            (video_id, _utc_now_iso(), status, row_id),
        )
        self.conn.commit()

    def mark_video_failed(self, row_id: int, *, error: str) -> None:
        meta = {"error": error, "failed_at": _utc_now_iso()}
        self.conn.execute(
            "UPDATE videos SET status=?, metadata_json=? WHERE id=?",
            ("failed", json.dumps(meta, ensure_ascii=False), row_id),
        )
        self.conn.commit()

    def recent_titles(self, limit: int = 50) -> List[str]:
        cur = self.conn.execute(
            "SELECT title FROM videos WHERE title IS NOT NULL ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [r["title"] for r in cur.fetchall() if r["title"]]

    def recent_descriptions(self, limit: int = 50) -> List[str]:
        cur = self.conn.execute(
            "SELECT description FROM videos WHERE description IS NOT NULL ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [r["description"] for r in cur.fetchall() if r["description"]]

    def recent_hashtag_sets(self, limit: int = 50) -> List[List[str]]:
        cur = self.conn.execute(
            "SELECT tags_json FROM videos WHERE tags_json IS NOT NULL ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        sets: List[List[str]] = []
        for r in cur.fetchall():
            try:
                tags = json.loads(r["tags_json"])
                if isinstance(tags, list):
                    sets.append([str(x) for x in tags])
            except Exception:
                continue
        return sets

    # ------------------ Provider health ------------------
    def get_provider_health(self, provider_key: str) -> ProviderHealth:
        cur = self.conn.execute(
            "SELECT provider_key, fail_count, cooldown_until, last_error FROM provider_health WHERE provider_key=?",
            (provider_key,),
        )
        row = cur.fetchone()
        if not row:
            return ProviderHealth(provider_key, 0, None, None)
        return ProviderHealth(
            provider_key=row["provider_key"],
            fail_count=int(row["fail_count"]),
            cooldown_until=row["cooldown_until"],
            last_error=row["last_error"],
        )

    def provider_on_success(self, provider_key: str) -> None:
        self.conn.execute(
            "INSERT INTO provider_health(provider_key, fail_count, cooldown_until, last_error, updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(provider_key) DO UPDATE SET fail_count=0, cooldown_until=NULL, last_error=NULL, updated_at=excluded.updated_at",
            (provider_key, 0, None, None, _utc_now_iso()),
        )
        self.conn.commit()

    def provider_on_failure(self, provider_key: str, *, error: str, cooldown_seconds: int) -> ProviderHealth:
        prev = self.get_provider_health(provider_key)
        fail_count = prev.fail_count + 1
        cooldown_until: Optional[str] = prev.cooldown_until
        if fail_count >= 3:
            cooldown_until_dt = datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)
            cooldown_until = cooldown_until_dt.replace(microsecond=0).isoformat()
        self.conn.execute(
            "INSERT INTO provider_health(provider_key, fail_count, cooldown_until, last_error, updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(provider_key) DO UPDATE SET fail_count=excluded.fail_count, cooldown_until=excluded.cooldown_until, last_error=excluded.last_error, updated_at=excluded.updated_at",
            (provider_key, fail_count, cooldown_until, error[:2000], _utc_now_iso()),
        )
        self.conn.commit()
        return ProviderHealth(provider_key, fail_count, cooldown_until, error[:2000])

    # ------------------ Bandit arms ------------------
    def get_arm(self, arm_type: str, arm_value: str) -> Tuple[float, float]:
        cur = self.conn.execute(
            "SELECT alpha, beta FROM bandit_arms WHERE arm_type=? AND arm_value=?",
            (arm_type, arm_value),
        )
        row = cur.fetchone()
        if not row:
            self.conn.execute(
                "INSERT OR IGNORE INTO bandit_arms(arm_type, arm_value, alpha, beta, updated_at) VALUES(?,?,?,?,?)",
                (arm_type, arm_value, 1.0, 1.0, _utc_now_iso()),
            )
            self.conn.commit()
            return (1.0, 1.0)
        return (float(row["alpha"]), float(row["beta"]))

    def update_arm(self, arm_type: str, arm_value: str, *, alpha: float, beta: float) -> None:
        self.conn.execute(
            "INSERT INTO bandit_arms(arm_type, arm_value, alpha, beta, updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(arm_type, arm_value) DO UPDATE SET alpha=excluded.alpha, beta=excluded.beta, updated_at=excluded.updated_at",
            (arm_type, arm_value, alpha, beta, _utc_now_iso()),
        )
        self.conn.commit()

    # ------------------ Run reports ------------------
    def start_run(self, run_id: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO run_reports(run_id, started_at, finished_at, status, report_json) VALUES(?,?,?,?,?)",
            (run_id, _utc_now_iso(), None, "running", None),
        )
        self.conn.commit()

    def finish_run(self, run_id: str, status: str, report: Dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE run_reports SET finished_at=?, status=?, report_json=? WHERE run_id=?",
            (_utc_now_iso(), status, json.dumps(report, ensure_ascii=False), run_id),
        )
        self.conn.commit()

    # ------------------ Metrics persistence ------------------
    def update_video_metrics(self, *, video_id: str, metrics: Dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE videos SET metrics_json=? WHERE video_id=?",
            (json.dumps(metrics, ensure_ascii=False), video_id),
        )
        self.conn.commit()

    def list_videos_missing_metrics(self, days_back: int) -> List[Dict[str, Any]]:
        since = datetime.now(timezone.utc) - timedelta(days=days_back)
        since_iso = since.replace(microsecond=0).isoformat()
        cur = self.conn.execute(
            "SELECT id, video_id, kind, publish_at, created_at FROM videos "
            "WHERE video_id IS NOT NULL AND (metrics_json IS NULL OR metrics_json='') "
            "AND created_at >= ?",
            (since_iso,),
        )
        return [dict(r) for r in cur.fetchall()]

    def list_recent_videos(self, days_back: int) -> List[Dict[str, Any]]:
        since = datetime.now(timezone.utc) - timedelta(days=days_back)
        since_iso = since.replace(microsecond=0).isoformat()
        cur = self.conn.execute(
            "SELECT * FROM videos WHERE created_at >= ? AND video_id IS NOT NULL",
            (since_iso,),
        )
        return [dict(r) for r in cur.fetchall()]
