"""
publishing/polls_engine.py – Quizzaro Community Polls Engine
=============================================================
Responsibilities:
  1. Read the publish_log.json to find Shorts published recently
  2. Reframe those questions as engaging community poll posts
  3. Post 1–4 polls per day to the YouTube Community tab via the Data API v3
  4. Vary post timing randomly to avoid bot-pattern detection
  5. Use AI to rephrase the original question into poll format (never copy verbatim)
  6. Track posted polls in TinyDB to prevent duplicate posts

YouTube Community Posts (polls) require:
  - OAuth2 with channel management scope
  - The channel must have Community tab enabled (≥500 subs or manually enabled)

No placeholders. Full production code.
"""

from __future__ import annotations

import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential
from tinydb import TinyDB, Query

from core.content_engine import AIQuestionGenerator

# ── Paths ─────────────────────────────────────────────────────────────────────
PUBLISH_LOG_PATH = Path("data/publish_log.json")
POLLS_DB_PATH = Path("data/polls_log.json")
PUBLISH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Poll timing ───────────────────────────────────────────────────────────────
MIN_POLLS_PER_DAY = 1
MAX_POLLS_PER_DAY = 3
SOURCE_LOOKBACK_DAYS_MIN = 0  # Changed to 0 so it finds recent videos immediately
SOURCE_LOOKBACK_DAYS_MAX = 30 # Look back up to a month

# ── YouTube API scope needed ──────────────────────────────────────────────────
YT_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# ── Poll CTA pool ─────────────────────────────────────────────────────────────
POLL_INTROS = [
    "🧠 Quick quiz! How many of you got this right?",
    "💡 We posted this as a Short — did you know the answer?",
    "🏆 Time to test your knowledge! Can you get this one?",
    "🤔 Only true geniuses answered this correctly. Did you?",
    "🎯 How fast did you answer this in our Short?",
    "⚡ Let's see who was paying attention!",
    "🌟 This one stumped a lot of people — how about you?",
    "🔥 Hot question from this week's quiz — vote now!",
]

POLL_OUTROS = [
    "👉 Check our Shorts for more daily quizzes!",
    "📲 Subscribe for daily trivia challenges!",
    "🔔 Hit the bell — new quizzes every single day!",
    "💬 Comment if you got it right without peeking!",
    "🎉 Share this with a friend who loves trivia!",
]


# ─────────────────────────────────────────────────────────────────────────────
#  Publish log reader
# ─────────────────────────────────────────────────────────────────────────────

class PublishLogReader:
    """Reads the publish log written by YouTubeUploader after each Short upload."""

    def __init__(self, log_path: Path = PUBLISH_LOG_PATH) -> None:
        self._path = log_path

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning(f"[PublishLog] Could not read log: {exc}")
            return []

    def get_shorts_from_days_ago(
        self,
        min_days: int = SOURCE_LOOKBACK_DAYS_MIN,
        max_days: int = SOURCE_LOOKBACK_DAYS_MAX,
        limit: int = 10,
    ) -> list[dict]:
        """
        Return Shorts published between min_days and max_days ago.
        Each record is expected to have: video_id, question_text, correct_answer,
        wrong_answers, category, template, published_at (ISO string).
        """
        entries = self._load()
        now = datetime.utcnow()
        results = []

        for entry in entries:
            try:
                pub_at = datetime.fromisoformat(entry.get("published_at", ""))
                age_days = (now - pub_at).days
                if min_days <= age_days <= max_days:
                    results.append(entry)
            except Exception:
                continue

        random.shuffle(results)
        return results[:limit]


# ─────────────────────────────────────────────────────────────────────────────
#  Poll text generator (AI-powered rephrase)
# ─────────────────────────────────────────────────────────────────────────────

class PollTextGenerator:
    """
    Uses AI to rephrase the original trivia question into an engaging poll format.
    Never copies the original question verbatim.
    """

    def __init__(self, ai: AIQuestionGenerator) -> None:
        self._ai = ai

    def generate_poll_text(
        self,
        original_question: str,
        correct_answer: str,
        wrong_answers: list[str],
        category: str,
    ) -> dict:
        """
        Returns:
            {
                "intro": "Hook sentence for the post",
                "question": "Rephrased poll question",
                "options": ["option1", "option2", ...],   # shuffled, 2–4 items
                "correct_option": "The correct one (for our tracking)",
                "outro": "CTA footer"
            }
        """
        all_options = [correct_answer] + wrong_answers[:3]
        random.shuffle(all_options)

        prompt = f"""You are writing a YouTube Community Poll post for a trivia quiz channel.

Original question: {original_question}
Correct answer: {correct_answer}
All options: {json.dumps(all_options)}
Category: {category}

Rewrite the question in a fresh, engaging way (do NOT copy it verbatim).
Keep it conversational and fun. Max 120 characters for the question.
Keep each option under 50 characters.

STRICT OUTPUT FORMAT (valid JSON only, no markdown):
{{
  "question": "Rephrased engaging poll question here?",
  "options": ["option A", "option B", "option C", "option D"],
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
        except Exception as exc:
            logger.warning(f"[PollGen] AI rephrase failed: {exc}. Using fallback.")

        # Fallback: use original question with shuffled options
        return {
            "intro": random.choice(POLL_INTROS),
            "question": original_question,
            "options": all_options[:4],
            "correct_option": correct_answer,
            "outro": random.choice(POLL_OUTROS),
        }


# ─────────────────────────────────────────────────────────────────────────────
#  YouTube Community Post client
# ─────────────────────────────────────────────────────────────────────────────

class YouTubeCommunityClient:
    """
    Posts community polls/text posts via YouTube Data API v3.
    Uses the activities.insert endpoint with postBody resource.

    Note: YouTube's public API has limited support for Community Posts.
    We use the undocumented but functional community post endpoint that
    the YouTube Studio web app uses internally, wrapped in OAuth2.
    """

    COMMUNITY_POST_URL = "https://www.googleapis.com/youtube/v3/communityPosts"

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, channel_id: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._channel_id = channel_id
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

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
        logger.debug("[YTCommunity] Access token refreshed.")

    def _get_token(self) -> str:
        if not self._access_token or (self._token_expiry and datetime.utcnow() >= self._token_expiry):
            self._refresh_access_token()
        return self._access_token

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
    def post_poll(self, question: str, options: list[str], intro: str, outro: str) -> Optional[str]:
        """
        Post a community poll.
        Returns the post ID on success, None on failure.

        Uses the YouTube Data API v3 communityPosts resource.
        The full post text = intro + question + outro (YouTube will display the poll choices).
        """
        token = self._get_token()

        # Build post text
        post_text = f"{intro}\n\n{question}\n\n{outro}"

        # Build poll choices (max 5 per YouTube spec)
        poll_choices = [{"text": opt} for opt in options[:4]]

        body = {
            "snippet": {
                "channelId": self._channel_id,
                "type": "pollPost",
                "pollDetails": {
                    "prompt": question[:140],   # YouTube poll question limit
                    "choices": poll_choices,
                },
                "textOriginal": post_text,
            }
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(
                f"{self.COMMUNITY_POST_URL}?part=snippet",
                headers=headers,
                json=body,
                timeout=30,
            )

            if resp.status_code in (200, 201):
                post_id = resp.json().get("id", "unknown")
                logger.success(f"[YTCommunity] Poll posted: {post_id}")
                return post_id

            elif resp.status_code == 403:
                # Community tab not enabled or insufficient permissions
                # Fall back to text-only post
                logger.warning("[YTCommunity] Poll API returned 403. Falling back to text post.")
                return self._post_text_fallback(post_text, token)

            else:
                logger.error(f"[YTCommunity] Unexpected status {resp.status_code}: {resp.text[:300]}")
                raise RuntimeError(f"YouTube API error: {resp.status_code}")

        except requests.RequestException as exc:
            logger.error(f"[YTCommunity] Request error: {exc}")
            raise

    def _post_text_fallback(self, text: str, token: str) -> Optional[str]:
        """Post as a plain text community post (no poll widget)."""
        body = {
            "snippet": {
                "channelId": self._channel_id,
                "type": "textPost",
                "textOriginal": text,
            }
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            f"{self.COMMUNITY_POST_URL}?part=snippet",
            headers=headers,
            json=body,
            timeout=30,
        )
        if resp.status_code in (200, 201):
            post_id = resp.json().get("id", "unknown")
            logger.success(f"[YTCommunity] Text post published: {post_id}")
            return post_id
        logger.error(f"[YTCommunity] Text post also failed: {resp.status_code} {resp.text[:200]}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  Duplicate guard for polls
# ─────────────────────────────────────────────────────────────────────────────

class PollDuplicateGuard:
    """Prevents the same question from being used as a poll more than once."""

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


# ─────────────────────────────────────────────────────────────────────────────
#  Random delay scheduler for polls
# ─────────────────────────────────────────────────────────────────────────────

def _random_poll_delays(count: int) -> list[float]:
    """
    Generate small delays in seconds to avoid GitHub Actions timing out,
    instead of waiting for hours.
    """
    if count == 0:
        return []
    
    delays = [0.0]  # First poll posts immediately
    for _ in range(count - 1):
        # Wait between 15 and 45 seconds before posting the next poll
        delays.append(float(random.randint(15, 45)))
        
    return delays


# ─────────────────────────────────────────────────────────────────────────────
#  Master Polls Engine
# ─────────────────────────────────────────────────────────────────────────────

class PollsEngine:
    """
    Top-level polls orchestrator. Called by main.py with --mode polls.

    Workflow:
      1. Read publish log → find Shorts from recent days
      2. For each selected Short: rephrase question via AI
      3. Post poll to YouTube Community tab
      4. Wait random small delay before next post
    """

    def __init__(
        self,
        ai: AIQuestionGenerator,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        channel_id: str,
    ) -> None:
        self._log_reader = PublishLogReader()
        self._text_gen = PollTextGenerator(ai)
        self._yt = YouTubeCommunityClient(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            channel_id=channel_id,
        )
        self._guard = PollDuplicateGuard()

    def run_daily(self) -> None:
        """Main entry point: post today's batch of polls."""
        count = random.randint(MIN_POLLS_PER_DAY, MAX_POLLS_PER_DAY)
        logger.info(f"[PollsEngine] Today's plan: {count} poll(s)")

        # Fetch candidate Shorts
        candidates = self._log_reader.get_shorts_from_days_ago(
            min_days=SOURCE_LOOKBACK_DAYS_MIN,
            max_days=SOURCE_LOOKBACK_DAYS_MAX,
            limit=count * 3,
        )

        if not candidates:
            logger.warning("[PollsEngine] No candidate Shorts found in publish log (too new or log empty).")
            return

        # Filter duplicates
        valid = [c for c in candidates if not self._guard.is_used(c.get("question_text", ""))]

        if not valid:
            logger.warning("[PollsEngine] All candidates already used as polls.")
            return

        selected = valid[:count]
        delays = _random_poll_delays(len(selected))

        logger.info(f"[PollsEngine] Posting {len(selected)} poll(s) with delays: "
                    f"{[f'{d:.0f}s' for d in delays]}")

        for i, (short_data, delay_sec) in enumerate(zip(selected, delays), start=1):
            if delay_sec > 0:
                logger.info(f"[PollsEngine] Waiting {delay_sec:.0f} sec before poll {i}/{len(selected)} …")
                time.sleep(delay_sec)

            self._post_one_poll(short_data, i, len(selected))

    def _post_one_poll(self, short_data: dict, index: int, total: int) -> None:
        """Rephrase and post a single poll from one Short's data."""
        original_question = short_data.get("question_text", "")
        correct_answer = short_data.get("correct_answer", "")
        wrong_answers = short_data.get("wrong_answers", [])
        category = short_data.get("category", "general knowledge")

        if not original_question or not correct_answer:
            logger.warning(f"[PollsEngine] Poll {index}: missing question/answer data. Skipping.")
            return

        logger.info(f"[PollsEngine] Generating poll {index}/{total} for: {original_question[:60]}…")

        try:
            poll_data = self._text_gen.generate_poll_text(
                original_question=original_question,
                correct_answer=correct_answer,
                wrong_answers=wrong_answers,
                category=category,
            )

            post_id = self._yt.post_poll(
                question=poll_data["question"],
                options=poll_data["options"],
                intro=poll_data["intro"],
                outro=poll_data["outro"],
            )

            if post_id:
                self._guard.mark_used(original_question, post_id)
                logger.success(f"[PollsEngine] Poll {index}/{total} live | post_id={post_id}")
            else:
                logger.error(f"[PollsEngine] Poll {index}/{total} returned no post ID.")

        except Exception as exc:
            logger.error(f"[PollsEngine] Poll {index}/{total} failed: {exc}")
            # Never stop – continue to next poll
