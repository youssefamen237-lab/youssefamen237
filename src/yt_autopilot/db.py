\
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .settings import DATA_DIR
from .state import iso_utc, parse_iso_utc, utc_now


DB_PATH = DATA_DIR / "channel.sqlite3"


def _connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at_utc TEXT NOT NULL,
                template_id TEXT NOT NULL,
                category TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                options_json TEXT,
                question_hash TEXT NOT NULL,
                llm_provider TEXT NOT NULL
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_created_at ON questions(created_at_utc);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_hash ON questions(question_hash);")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at_utc TEXT NOT NULL,
                kind TEXT NOT NULL,
                video_id TEXT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                tags_json TEXT,
                hashtags_json TEXT,
                template_id TEXT,
                voice_id TEXT,
                cta_id TEXT,
                question_id INTEGER,
                duration_seconds REAL,
                scheduled_for_utc TEXT,
                published_at_utc TEXT,
                status TEXT NOT NULL,
                error TEXT,
                FOREIGN KEY(question_id) REFERENCES questions(id)
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_uploads_created_at ON uploads(created_at_utc);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_uploads_video_id ON uploads(video_id);")
        conn.commit()
    finally:
        conn.close()


def normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = " ".join(s.split())
    return s


def hash_question(question: str, answer: str) -> str:
    h = hashlib.sha256()
    h.update(normalize_text(question).encode("utf-8"))
    h.update(b"||")
    h.update(normalize_text(answer).encode("utf-8"))
    return h.hexdigest()


@dataclass
class QuestionItem:
    template_id: str
    category: str
    difficulty: str
    question: str
    answer: str
    options: Optional[List[str]]
    llm_provider: str


def insert_question(item: QuestionItem) -> int:
    init_db()
    qh = hash_question(item.question, item.answer)
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO questions (created_at_utc, template_id, category, difficulty, question, answer, options_json, question_hash, llm_provider)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                iso_utc(utc_now()),
                item.template_id,
                item.category,
                item.difficulty,
                item.question,
                item.answer,
                json.dumps(item.options, ensure_ascii=False) if item.options is not None else None,
                qh,
                item.llm_provider,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def fetch_recent_question_hashes(days: int) -> List[str]:
    init_db()
    since = utc_now() - timedelta(days=days)
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT question_hash FROM questions WHERE created_at_utc >= ?",
            (iso_utc(since),),
        )
        return [r["question_hash"] for r in cur.fetchall()]
    finally:
        conn.close()


def find_duplicate_question(question: str, answer: str, days: int) -> bool:
    init_db()
    qh = hash_question(question, answer)
    since = utc_now() - timedelta(days=days)
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM questions WHERE question_hash = ? AND created_at_utc >= ? LIMIT 1",
            (qh, iso_utc(since)),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def create_upload_record(
    *,
    kind: str,
    title: str,
    description: str,
    tags: Optional[List[str]],
    hashtags: Optional[List[str]],
    template_id: Optional[str],
    voice_id: Optional[str],
    cta_id: Optional[str],
    question_id: Optional[int],
    duration_seconds: Optional[float],
    scheduled_for_utc: Optional[str],
) -> int:
    init_db()
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO uploads (
                created_at_utc, kind, video_id, title, description, tags_json, hashtags_json,
                template_id, voice_id, cta_id, question_id, duration_seconds, scheduled_for_utc,
                published_at_utc, status, error
            )
            VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)
            """,
            (
                iso_utc(utc_now()),
                kind,
                title,
                description,
                json.dumps(tags, ensure_ascii=False) if tags else None,
                json.dumps(hashtags, ensure_ascii=False) if hashtags else None,
                template_id,
                voice_id,
                cta_id,
                question_id,
                float(duration_seconds) if duration_seconds is not None else None,
                scheduled_for_utc,
                "created",
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def mark_upload_success(upload_id: int, video_id: str, published_at_utc: Optional[str] = None) -> None:
    init_db()
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE uploads SET status = ?, video_id = ?, published_at_utc = ?, error = NULL WHERE id = ?",
            ("uploaded", video_id, published_at_utc or iso_utc(utc_now()), int(upload_id)),
        )
        conn.commit()
    finally:
        conn.close()


def mark_upload_failed(upload_id: int, error: str) -> None:
    init_db()
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE uploads SET status = ?, error = ? WHERE id = ?",
            ("failed", (error or "")[:2000], int(upload_id)),
        )
        conn.commit()
    finally:
        conn.close()


def list_recent_uploads(days: int = 30) -> List[Dict[str, Any]]:
    init_db()
    since = utc_now() - timedelta(days=days)
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM uploads WHERE created_at_utc >= ? ORDER BY created_at_utc DESC",
            (iso_utc(since),),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def fetch_recent_questions(days: int) -> List[Dict[str, Any]]:
    init_db()
    since = utc_now() - timedelta(days=days)
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, created_at_utc, question, answer, template_id, category FROM questions WHERE created_at_utc >= ? ORDER BY created_at_utc DESC",
            (iso_utc(since),),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_uploaded_videos(days: int = 90) -> List[Dict[str, Any]]:
    init_db()
    since = utc_now() - timedelta(days=days)
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM uploads WHERE created_at_utc >= ? AND status = 'uploaded' AND video_id IS NOT NULL ORDER BY created_at_utc DESC",
            (iso_utc(since),),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
