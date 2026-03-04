"""
publishing/polls_engine.py – Quizzaro Community Polls Engine
"""
from __future__ import annotations

import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from loguru import logger
from tinydb import TinyDB, Query

from core.content_engine import AIQuestionGenerator

PUBLISH_LOG_PATH = Path("data/publish_log.json")
POLLS_DB_PATH = Path("data/polls_log.json")
PUBLISH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

POLL_INTROS = ["🧠 Quick quiz! How many of you got this right?", "💡 We posted this as a Short — did you know the answer?", "🏆 Time to test your knowledge! Can you get this one?"]
POLL_OUTROS = ["👉 Check our Shorts for more daily quizzes!", "📲 Subscribe for daily trivia challenges!", "💬 Comment if you got it right without peeking!"]

class PublishLogReader:
    def __init__(self, log_path: Path = PUBLISH_LOG_PATH) -> None:
        self._path = log_path

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def get_recent_shorts(self, limit: int = 10) -> list[dict]:
        entries = self._load()
        if not entries:
            return []
        recent = entries[-limit:]
        random.shuffle(recent)
        return recent

class PollTextGenerator:
    def __init__(self, ai: AIQuestionGenerator) -> None:
        self._ai = ai

    def generate_poll_text(self, original_question: str, correct_answer: str, wrong_answers: list[str], category: str) -> dict:
        all_options = [correct_answer] + wrong_answers[:3]
        random.shuffle(all_options)
        prompt = f"""You are writing a YouTube Community Poll.
Original: {original_question}
Correct: {correct_answer}
Options: {json.dumps(all_options)}
STRICT JSON:
{{
  "question": "Rephrased poll question?",
  "options": ["A", "B", "C", "D"],
  "correct_option": "{correct_answer}"
}}"""
        try:
            import re
            raw = self._ai.generate_raw(prompt)
            raw = re.sub(r"```json|```", "", raw).strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return {
                    "intro": random.choice(POLL_INTROS),
                    "question": data.get("question", original_question),
                    "options": data.get("options", all_options)[:4],
                    "correct_option": data.get("correct_option", correct_answer),
                    "outro": random.choice(POLL_OUTROS),
                }
        except Exception:
            pass
        return {
            "intro": random.choice(POLL_INTROS),
            "question": original_question,
            "options": all_options[:4],
            "correct_option": correct_answer,
            "outro": random.choice(POLL_OUTROS),
        }

class YouTubeCommunityClient:
    COMMUNITY_POST_URL = "https://www.googleapis.com/youtube/v3/communityPosts"

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, channel_id: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._channel_id = channel_id
        self._access_token = None
        self._token_expiry = None

    def _refresh_access_token(self) -> None:
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expiry = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600) - 60)

    def _get_token(self) -> str:
        if not self._access_token or (self._token_expiry and datetime.utcnow() >= self._token_expiry):
            self._refresh_access_token()
        return self._access_token

    def post_poll(self, question: str, options: list[str], intro: str, outro: str) -> Optional[str]:
        token = self._get_token()
        post_text = f"{intro}\n\n{question}\n\n{outro}"
        poll_choices = [{"text": opt} for opt in options[:4]]

        body = {
            "snippet": {
                "channelId": self._channel_id,
                "type": "pollPost",
                "pollDetails": {
                    "prompt": question[:140],
                    "choices": poll_choices,
                },
                "textOriginal": post_text,
            }
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        
        resp = requests.post(f"{self.COMMUNITY_POST_URL}?part=snippet", headers=headers, json=body, timeout=30)
        
        if resp.status_code in (200, 201):
            return resp.json().get("id", "unknown")
        elif resp.status_code == 403:
            return self._post_text_fallback(post_text, token)
        else:
            raise RuntimeError(f"YouTube API Error {resp.status_code}: {resp.text}")

    def _post_text_fallback(self, text: str, token: str) -> Optional[str]:
        body = {
            "snippet": {
                "channelId": self._channel_id,
                "type": "textPost",
                "textOriginal": text,
            }
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        resp = requests.post(f"{self.COMMUNITY_POST_URL}?part=snippet", headers=headers, json=body, timeout=30)
        
        if resp.status_code in (200, 201):
            return resp.json().get("id", "unknown")
            
        raise RuntimeError(f"YouTube Fallback Error {resp.status_code}: {resp.text}")

class PollDuplicateGuard:
    def __init__(self) -> None:
        self._db = TinyDB(POLLS_DB_PATH)
        self._table = self._db.table("posted_polls")

    def is_used(self, question_text: str) -> bool:
        import hashlib
        fp = hashlib.sha256(question_text.lower().strip().encode()).hexdigest()
        Q = Query()
        return bool(self._table.search(Q.fingerprint == fp))

    def mark_used(self, question_text: str, post_id: str) -> None:
        import hashlib
        fp = hashlib.sha256(question_text.lower().strip().encode()).hexdigest()
        self._table.insert({
            "fingerprint": fp,
            "post_id": post_id,
            "posted_at": datetime.utcnow().isoformat(),
        })

class PollsEngine:
    def __init__(self, ai: AIQuestionGenerator, client_id: str, client_secret: str, refresh_token: str, channel_id: str) -> None:
        self._log_reader = PublishLogReader()
        self._text_gen = PollTextGenerator(ai)
        self._yt = YouTubeCommunityClient(client_id, client_secret, refresh_token, channel_id)
        self._guard = PollDuplicateGuard()

    def run_daily(self) -> None:
        count = random.randint(1, 3)
        logger.info(f"[PollsEngine] Today's plan: {count} poll(s)")

        candidates = self._log_reader.get_recent_shorts(limit=count * 3)
        if not candidates:
            logger.warning("[PollsEngine] No shorts found in publish_log.json! Skipping polls for today.")
            return

        valid = [c for c in candidates if not self._guard.is_used(c.get("question_text", ""))]
        if not valid:
            logger.warning("[PollsEngine] All candidate shorts have already been posted as polls. Skipping.")
            return

        selected = valid[:count]
        
        for i, short_data in enumerate(selected, start=1):
            self._post_one_poll(short_data, i, len(selected))
            if i < len(selected):
                time.sleep(15)

    def _post_one_poll(self, short_data: dict, index: int, total: int) -> None:
        original_question = short_data.get("question_text", "")
        correct_answer = short_data.get("correct_answer", "")
        wrong_answers = short_data.get("wrong_answers", [])
        category = short_data.get("category", "general knowledge")

        poll_data = self._text_gen.generate_poll_text(original_question, correct_answer, wrong_answers, category)
        post_id = self._yt.post_poll(poll_data["question"], poll_data["options"], poll_data["intro"], poll_data["outro"])

        if post_id:
            self._guard.mark_used(original_question, post_id)
            logger.success(f"[PollsEngine] Poll {index}/{total} live | post_id={post_id}")
