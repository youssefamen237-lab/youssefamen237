"""
publishing/polls_engine.py – Quizzaro Community Polls Engine
"""
from __future__ import annotations

import json
import random
import re
import requests
from loguru import logger
from core.content_engine import AIQuestionGenerator

class YouTubeCommunityClient:
    # YouTube Data API endpoint for Community Posts
    COMMUNITY_POST_URL = "https://www.googleapis.com/youtube/v3/communityPosts"

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, channel_id: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._channel_id = channel_id

    def _get_token(self) -> str:
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
        return resp.json()["access_token"]

    def post_poll(self, question: str, options: list[str]) -> None:
        token = self._get_token()
        post_text = f"🧠 Quick quiz! How many of you got this right?\n\n{question}\n\n👉 Check our Shorts for more daily quizzes!"
        
        body = {
            "snippet": {
                "channelId": self._channel_id,
                "type": "pollPost",
                "pollDetails": {
                    "prompt": question[:140],
                    "choices": [{"text": opt} for opt in options[:4]]
                },
                "textOriginal": post_text,
            }
        }
        
        headers = {
            "Authorization": f"Bearer {token}", 
            "Content-Type": "application/json"
        }
        
        logger.info("Sending poll data directly to YouTube API...")
        resp = requests.post(f"{self.COMMUNITY_POST_URL}?part=snippet", headers=headers, json=body, timeout=30)
        
        if resp.status_code in (200, 201):
            logger.success(f"Poll posted successfully! ID: {resp.json().get('id', 'unknown')}")
        else:
            # هنا هيطبع الخطأ الحقيقي اللي بيمنع النشر
            raise RuntimeError(f"YouTube API Error {resp.status_code}: {resp.text}")


class PollsEngine:
    def __init__(self, ai: AIQuestionGenerator, client_id: str, client_secret: str, refresh_token: str, channel_id: str) -> None:
        self._ai = ai
        self._yt = YouTubeCommunityClient(client_id, client_secret, refresh_token, channel_id)

    def run_daily(self) -> None:
        logger.info("Generating a fresh poll question...")
        prompt = """Create an engaging trivia question for a YouTube poll.
STRICT JSON OUTPUT ONLY:
{
  "question": "Which of these is the largest planet?",
  "options": ["Mars", "Jupiter", "Saturn", "Earth"]
}"""
        
        raw = self._ai.generate_raw(prompt)
        raw = re.sub(r"```json|```", "", raw).strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        
        if not match:
            raise ValueError("AI failed to generate valid JSON.")
            
        data = json.loads(match.group())
        
        logger.info(f"Question generated: {data['question']}")
        
        # Post the poll directly
        self._yt.post_poll(data["question"], data["options"])
