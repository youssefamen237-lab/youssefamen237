"""
core/anti_duplicate.py – Quizzaro Anti-Duplicate Engine
=========================================================
Single TinyDB-backed service used by:
  - QuestionBank     → 15-day no-repeat for questions
  - BackgroundManager → 10-day no-repeat for video clips
  - MusicEngine      →  7-day no-repeat for music tracks

All fingerprints are SHA-256 of the canonical identifier.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path

from tinydb import TinyDB, Query

DB_DIR = Path("data")
DB_DIR.mkdir(parents=True, exist_ok=True)

# Separate tables for each resource type — same DB file, different tables
MAIN_DB_PATH = DB_DIR / "anti_duplicate.json"


class AntiDuplicate:

    def __init__(self, db_path: Path = MAIN_DB_PATH) -> None:
        self._db = TinyDB(db_path)
        self._questions = self._db.table("questions")
        self._backgrounds = self._db.table("backgrounds")
        self._music = self._db.table("music")

    # ── Internal helpers ───────────────────────────────────────────────────

    @staticmethod
    def _fp(value: str) -> str:
        return hashlib.sha256(value.lower().strip().encode()).hexdigest()

    def _is_used(self, table, identifier: str, repeat_days: int) -> bool:
        fp = self._fp(identifier)
        Q = Query()
        rows = table.search(Q.fp == fp)
        if not rows:
            return False
        delta = datetime.utcnow() - datetime.fromisoformat(rows[0]["used_at"])
        return delta.days < repeat_days

    def _mark_used(self, table, identifier: str, extra: dict | None = None) -> None:
        fp = self._fp(identifier)
        Q = Query()
        entry = {"fp": fp, "identifier": identifier, "used_at": datetime.utcnow().isoformat()}
        if extra:
            entry.update(extra)
        if table.search(Q.fp == fp):
            table.update(entry, Q.fp == fp)
        else:
            table.insert(entry)

    # ── Questions (15-day rule) ────────────────────────────────────────────

    def is_question_used(self, question_text: str) -> bool:
        return self._is_used(self._questions, question_text, repeat_days=15)

    def mark_question_used(self, question_text: str, question_id: str = "") -> None:
        self._mark_used(self._questions, question_text, extra={"question_id": question_id})

    # ── Backgrounds (10-day rule) ──────────────────────────────────────────

    def is_background_used(self, video_id: str) -> bool:
        return self._is_used(self._backgrounds, video_id, repeat_days=10)

    def mark_background_used(self, video_id: str, source: str = "") -> None:
        self._mark_used(self._backgrounds, video_id, extra={"source": source})

    # ── Music (7-day rule) ─────────────────────────────────────────────────

    def is_music_used(self, sound_id: str) -> bool:
        return self._is_used(self._music, sound_id, repeat_days=7)

    def mark_music_used(self, sound_id: str) -> None:
        self._mark_used(self._music, sound_id)
