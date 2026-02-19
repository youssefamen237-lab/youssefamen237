import sqlite3
import datetime
import json
from pathlib import Path
from .config import Config
import logging

logger = logging.getLogger("duplicate_manager")
handler = logging.FileHandler(Config.LOG_DIR / "duplicate_manager.log")
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

class DuplicateManager:
    def __init__(self):
        self.conn = sqlite3.connect(Config.DB_PATH)
        self._create_tables()

    def _create_tables(self):
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT UNIQUE,
                used_at TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS titles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT UNIQUE,
                used_at TIMESTAMP
            )
        """)
        self.conn.commit()

    def is_recent_question(self, question: str, days: int = 15) -> bool:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT used_at FROM questions
            WHERE question = ?
        """, (question,))
        row = cur.fetchone()
        if not row:
            return False
        used_at = datetime.datetime.fromisoformat(row[0])
        return (datetime.datetime.utcnow() - used_at).days < days

    def register_question(self, question: str):
        now = datetime.datetime.utcnow().isoformat()
        try:
            cur = self.conn.cursor()
            cur.execute("""
                INSERT OR IGNORE INTO questions (question, used_at)
                VALUES (?, ?)
            """, (question, now))
            self.conn.commit()
            logger.info(f"Registered question.")
        except Exception as e:
            logger.exception(f"Failed to register question: {e}")

    def prune_questions(self, keep_days: int = 30):
        threshold = (datetime.datetime.utcnow() - datetime.timedelta(days=keep_days)).isoformat()
        cur = self.conn.cursor()
        cur.execute("""
            DELETE FROM questions WHERE used_at < ?
        """, (threshold,))
        self.conn.commit()
        logger.info("Pruned old questions.")

    def is_recent_title(self, title: str, days: int = 30) -> bool:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT used_at FROM titles WHERE title = ?
        """, (title,))
        row = cur.fetchone()
        if not row:
            return False
        used_at = datetime.datetime.fromisoformat(row[0])
        return (datetime.datetime.utcnow() - used_at).days < days

    def register_title(self, title: str):
        now = datetime.datetime.utcnow().isoformat()
        try:
            cur = self.conn.cursor()
            cur.execute("""
                INSERT OR IGNORE INTO titles (title, used_at)
                VALUES (?, ?)
            """, (title, now))
            self.conn.commit()
            logger.info("Registered title.")
        except Exception as e:
            logger.exception(f"Failed to register title: {e}")

    def close(self):
        self.conn.close()
