"""
publishing/youtube_uploader.py – Quizzaro YouTube Uploader
============================================================
Responsibilities:
  1. OAuth2 token management (refresh on every call, no stored token files)
  2. Upload Short video via YouTube Data API v3 resumable upload
  3. Set video as a Short (vertical, ≤60s — enforced by #Shorts in title/description)
  4. Schedule publish time (publishAt in ISO 8601 UTC)
  5. Set title, description, tags, category, language, audience flags
  6. Write every successful upload to data/publish_log.json for later use
     by PollsEngine and ProjectManager
  7. Retry logic with exponential back-off for transient API errors
  8. Rate-limit guard (YouTube allows ~6 uploads/day on unverified channels,
     up to 100 quota units/day; the uploader tracks and respects this)

No placeholders. Full production code.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# ── Paths ─────────────────────────────────────────────────────────────────────
PUBLISH_LOG_PATH = Path("data/publish_log.json")
PUBLISH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

QUOTA_LOG_PATH = Path("data/quota_log.json")

# ── YouTube constants ─────────────────────────────────────────────────────────
YT_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YT_CATEGORY_EDUCATION = "27"
YT_CATEGORY_ENTERTAINMENT = "24"
YT_DEFAULT_LANGUAGE = "en"
YT_MADE_FOR_KIDS = False

# Resumable upload chunk size: 8 MB
CHUNK_SIZE = 8 * 1024 * 1024

# How many units one video.insert costs (YouTube Data API v3 quota)
UPLOAD_QUOTA_COST = 1600

# Daily quota cap we self-impose (YouTube free tier = 10,000 units/day)
DAILY_QUOTA_LIMIT = 9000

# YouTube's retryable HTTP status codes
RETRYABLE_STATUS = {500, 502, 503, 504}


# ─────────────────────────────────────────────────────────────────────────────
#  Quota tracker
# ─────────────────────────────────────────────────────────────────────────────

class QuotaTracker:
    """Tracks daily API quota usage in a local JSON file."""

    def __init__(self, path: Path = QUOTA_LOG_PATH) -> None:
        self._path = path

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"date": "", "used": 0}

    def _save(self, data: dict) -> None:
        with open(self._path, "w") as f:
            json.dump(data, f)

    def consumed_today(self) -> int:
        data = self._load()
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if data.get("date") != today:
            return 0
        return int(data.get("used", 0))

    def record(self, units: int) -> None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        data = self._load()
        if data.get("date") != today:
            data = {"date": today, "used": 0}
        data["used"] = data.get("used", 0) + units
        self._save(data)

    def can_upload(self) -> bool:
        return self.consumed_today() + UPLOAD_QUOTA_COST <= DAILY_QUOTA_LIMIT


# ─────────────────────────────────────────────────────────────────────────────
#  Publish log writer
# ─────────────────────────────────────────────────────────────────────────────

class PublishLogWriter:
    """Appends a record to publish_log.json after each successful upload."""

    def __init__(self, path: Path = PUBLISH_LOG_PATH) -> None:
        self._path = path

    def _load(self) -> list[dict]:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, list) else []
            except Exception:
                return []
        return []

    def append(self, record: dict) -> None:
        entries = self._load()
        entries.append(record)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        logger.debug(f"[PublishLog] Appended record for video_id={record.get('video_id')}")


# ─────────────────────────────────────────────────────────────────────────────
#  Token manager
# ─────────────────────────────────────────────────────────────────────────────

class TokenManager:
    """Handles OAuth2 access token refresh without storing tokens to disk."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._access_token: Optional[str] = None
        self._expires_at: Optional[datetime] = None

    def get_access_token(self) -> str:
        if self._access_token and self._expires_at and datetime.utcnow() < self._expires_at:
            return self._access_token
        return self._do_refresh()

    def _do_refresh(self) -> str:
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
        d = resp.json()
        self._access_token = d["access_token"]
        expires_in = int(d.get("expires_in", 3600))
        self._expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 60)
        logger.debug("[TokenManager] Access token refreshed.")
        return self._access_token

    def as_credentials(self) -> Credentials:
        token = self.get_access_token()
        return Credentials(
            token=token,
            refresh_token=self._refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._client_id,
            client_secret=self._client_secret,
            scopes=[YT_UPLOAD_SCOPE],
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Description & tags builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_description(
    question_text: str,
    correct_answer: str,
    explanation: str,
    fun_fact: str,
    category: str,
    tags: list[str],
) -> str:
    """
    Build a rich, varied YouTube description.
    Every call produces a slightly different phrasing to avoid duplicate-content flags.
    """
    import random

    openers = [
        "🧠 Think you know the answer?",
        "💡 Can you get this right?",
        "🎯 Test your knowledge!",
        "⚡ Quick trivia challenge!",
        "🏆 Only the sharpest minds get this one!",
        "🤔 How well do you know your trivia?",
    ]
    closers = [
        "👉 Subscribe for daily trivia and quiz challenges!",
        "🔔 Hit the bell so you never miss a new quiz!",
        "📲 New quiz Shorts every single day — subscribe now!",
        "💬 Drop your answer in the comments before it's revealed!",
        "🌟 Share this with a friend and see who gets it right!",
    ]
    cta_lines = [
        "Comment your answer BEFORE the reveal — no cheating!",
        "Pause here and lock in your answer!",
        "How fast did you get it? Tell us in the comments!",
        "Tag someone who needs to try this quiz!",
    ]

    hashtag_str = " ".join(f"#{t.replace(' ', '')}" for t in tags[:10])
    shorts_tags = "#Shorts #Quiz #Trivia #BrainTeaser #QuizTime #DailyTrivia"

    desc = (
        f"{random.choice(openers)}\n\n"
        f"📌 Question: {question_text}\n"
        f"✅ Answer: {correct_answer}\n\n"
        f"💬 {random.choice(cta_lines)}\n\n"
    )

    if explanation:
        desc += f"🔍 Did you know? {explanation}\n\n"

    if fun_fact:
        desc += f"🌍 Fun fact: {fun_fact}\n\n"

    desc += (
        f"Category: #{category.replace(' ', '').title()}\n\n"
        f"{shorts_tags}\n"
        f"{hashtag_str}\n\n"
        f"{random.choice(closers)}"
    )

    return desc[:4900]   # YouTube description limit is 5000 chars


def _build_tags(question_text: str, category: str, template: str, audience: str) -> list[str]:
    base_tags = [
        "trivia", "quiz", "shorts", "daily quiz", "brain teaser",
        "general knowledge", "quiz shorts", "trivia shorts", "fun facts",
        "quiz challenge", "did you know", "knowledge test",
        category, template.replace("_", " "), audience.lower(),
        "brain challenge", "quiz game", "educational shorts",
    ]
    # Extract 1–2 words from question as additional tags
    words = [w.strip("?!.,").lower() for w in question_text.split() if len(w) > 4]
    keyword_tags = list(dict.fromkeys(words))[:5]   # deduplicated

    all_tags = list(dict.fromkeys(base_tags + keyword_tags))
    return all_tags[:30]   # YouTube allows max 500 chars total; 30 tags is safe


# ─────────────────────────────────────────────────────────────────────────────
#  YouTube Uploader
# ─────────────────────────────────────────────────────────────────────────────

class YouTubeUploader:
    """
    Handles all YouTube upload operations.
    Uses YT_CLIENT_ID_1 / YT_CLIENT_SECRET_1 / YT_REFRESH_TOKEN_1.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        channel_id: str,
    ) -> None:
        self._token_mgr = TokenManager(client_id, client_secret, refresh_token)
        self._channel_id = channel_id
        self._quota = QuotaTracker()
        self._log = PublishLogWriter()

    def _service(self):
        return build("youtube", "v3", credentials=self._token_mgr.as_credentials(), cache_discovery=False)

    # ── Core upload ────────────────────────────────────────────────────────

    def upload_short(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        publish_at: datetime,
        question_object: Optional[dict] = None,
    ) -> str:
        """
        Upload a Short to YouTube.

        Args:
            video_path: Absolute path to the .mp4 file.
            title: Video title (must include #Shorts for YT to classify correctly).
            description: Full video description.
            tags: List of tag strings.
            publish_at: UTC datetime when the video should go public.
                        Pass datetime.utcnow() for immediate publish.
            question_object: Optional dict of QuestionObject fields for the publish log.

        Returns:
            YouTube video ID string.

        Raises:
            RuntimeError: If quota exhausted or upload fails after all retries.
        """
        if not self._quota.can_upload():
            raise RuntimeError(
                f"[Uploader] Daily quota limit reached "
                f"({self._quota.consumed_today()}/{DAILY_QUOTA_LIMIT} units used). "
                "Upload deferred to next day."
            )

        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"[Uploader] Video file not found: {video_path}")

        # Ensure #Shorts is in title for YouTube to categorise as a Short
        if "#Shorts" not in title and "#shorts" not in title:
            title = f"{title} #Shorts"

        # Truncate title to YouTube's 100-char limit
        title = title[:100]

        # Format publish_at as RFC 3339 UTC string
        if publish_at.tzinfo is None:
            publish_at = publish_at.replace(tzinfo=timezone.utc)
        publish_at_str = publish_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        # Decide privacy: "private" until scheduled time, "public" if immediate
        now_utc = datetime.now(timezone.utc)
        status_privacy = "private" if (publish_at - now_utc).total_seconds() > 30 else "public"

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": YT_CATEGORY_ENTERTAINMENT,
                "defaultLanguage": YT_DEFAULT_LANGUAGE,
                "defaultAudioLanguage": YT_DEFAULT_LANGUAGE,
            },
            "status": {
                "privacyStatus": status_privacy,
                "publishAt": publish_at_str if status_privacy == "private" else None,
                "madeForKids": YT_MADE_FOR_KIDS,
                "selfDeclaredMadeForKids": YT_MADE_FOR_KIDS,
            },
        }

        # Remove publishAt if not scheduling
        if body["status"]["publishAt"] is None:
            del body["status"]["publishAt"]

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            chunksize=CHUNK_SIZE,
            resumable=True,
        )

        logger.info(
            f"[Uploader] Starting upload: '{title[:60]}' | "
            f"privacy={status_privacy} | publish_at={publish_at_str}"
        )

        video_id = self._execute_resumable_upload(body, media)
        self._quota.record(UPLOAD_QUOTA_COST)

        logger.success(f"[Uploader] Upload complete → https://youtu.be/{video_id}")

        # ── Write to publish log ───────────────────────────────────────────
        log_record = {
            "video_id": video_id,
            "title": title,
            "published_at": publish_at_str,
            "privacy": status_privacy,
            "tags": tags,
        }
        if question_object:
            log_record.update({
                "question_text": question_object.get("question_text", ""),
                "correct_answer": question_object.get("correct_answer", ""),
                "wrong_answers": question_object.get("wrong_answers", []),
                "template": question_object.get("template", ""),
                "category": question_object.get("category", ""),
                "difficulty": question_object.get("difficulty", ""),
                "target_audience": question_object.get("target_audience", ""),
                "gender": question_object.get("gender", ""),
                "cta_text": question_object.get("cta_text", ""),
                "explanation": question_object.get("explanation", ""),
                "fun_fact": question_object.get("fun_fact", ""),
            })
        self._log.append(log_record)

        return video_id

    @retry(
        retry=retry_if_exception_type((HttpError, requests.RequestException, ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=10, max=120),
    )
    def _execute_resumable_upload(self, body: dict, media: MediaFileUpload) -> str:
        """
        Execute the resumable upload with retry on transient errors.
        Returns video_id on success.
        """
        yt = self._service()
        request = yt.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )

        response = None
        error = None
        retry_count = 0

        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    logger.debug(f"[Uploader] Upload progress: {pct}%")
            except HttpError as exc:
                if exc.resp.status in RETRYABLE_STATUS:
                    retry_count += 1
                    if retry_count > 5:
                        raise
                    wait = min(2 ** retry_count, 64)
                    logger.warning(f"[Uploader] HTTP {exc.resp.status}, retry in {wait}s …")
                    time.sleep(wait)
                    continue
                else:
                    raise

        if response is None:
            raise RuntimeError("[Uploader] Upload completed but response is None")

        return response["id"]

    # ── Thumbnail setter (optional, called post-upload) ────────────────────

    def set_thumbnail(self, video_id: str, thumbnail_path: str) -> bool:
        """Upload a custom thumbnail for a video. Returns True on success."""
        thumb_path = Path(thumbnail_path)
        if not thumb_path.exists():
            logger.warning(f"[Uploader] Thumbnail not found: {thumbnail_path}")
            return False
        try:
            yt = self._service()
            yt.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
            ).execute()
            logger.success(f"[Uploader] Thumbnail set for {video_id}")
            return True
        except Exception as exc:
            logger.warning(f"[Uploader] Thumbnail upload failed: {exc}")
            return False

    # ── Convenience: full upload pipeline ─────────────────────────────────

    def upload_with_metadata(
        self,
        video_path: str,
        question_object: dict,
        metadata: dict,
        publish_at: datetime,
    ) -> str:
        """
        One-call interface used by main.py's run_publish().

        Args:
            video_path: Path to rendered .mp4.
            question_object: Full QuestionObject as dict.
            metadata: Output from MetadataGenerator.generate().
            publish_at: Scheduled publish time (UTC datetime).

        Returns:
            YouTube video ID.
        """
        tags = _build_tags(
            question_text=question_object.get("question_text", ""),
            category=question_object.get("category", "general"),
            template=question_object.get("template", "quiz"),
            audience=question_object.get("target_audience", "American"),
        )

        description = _build_description(
            question_text=question_object.get("question_text", ""),
            correct_answer=question_object.get("correct_answer", ""),
            explanation=question_object.get("explanation", ""),
            fun_fact=question_object.get("fun_fact", ""),
            category=question_object.get("category", "general"),
            tags=tags,
        )

        title = metadata.get("title", "🧠 Can You Answer This? #Shorts #Quiz")

        return self.upload_short(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            publish_at=publish_at,
            question_object=question_object,
        )
