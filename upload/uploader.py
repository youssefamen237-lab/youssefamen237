"""
upload/uploader.py
==================
YouTube Data API v3 video uploader with:
- Automatic metadata injection (title, description, tags, category).
- Resumable upload protocol (handles large files and network blips).
- Quota-aware client rotation (skips exhausted clients, tries next).
- Full DB logging of every attempt (success or failure).
"""

import http.client
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httplib2
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from config.settings import (
    CHANNEL_NAME,
    CTA_TEXT,
    DAILY_SHORTS_COUNT,
    YT_CATEGORY_ID,
    YT_DEFAULT_TAGS,
)
from database.db import Database
from upload.auth import QuotaExhaustedError, YouTubeAuthManager
from upload.quota_tracker import QuotaTracker
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger(__name__)

# Resumable upload chunk size (10 MB)
_CHUNK_SIZE: int = 10 * 1024 * 1024

# HTTP status codes that warrant a retry on upload
_RETRYABLE_STATUS: tuple = (500, 502, 503, 504)
_RETRYABLE_EXCEPTIONS: tuple = (
    httplib2.HttpLib2Error,
    IOError,
    http.client.NotConnected,
    http.client.IncompleteRead,
    http.client.ImproperConnectionState,
    http.client.CannotSendRequest,
    http.client.CannotSendHeader,
    http.client.ResponseNotReady,
    http.client.BadStatusLine,
)

# Max resumable-upload retry attempts (separate from our outer retry decorator)
_MAX_RESUMABLE_RETRIES: int = 5


@dataclass
class UploadResult:
    """
    Outcome of one YouTube upload attempt.

    Attributes
    ----------
    success          : True if the video was accepted by YouTube.
    youtube_video_id : YouTube's assigned video ID (e.g. 'dQw4w9WgXcQ').
    youtube_url      : Full watch URL.
    client_index     : Which OAuth client was used (1 | 2 | 3).
    error_message    : Populated on failure.
    """
    success:          bool
    youtube_video_id: Optional[str] = None
    youtube_url:      Optional[str] = None
    client_index:     int = 0
    error_message:    Optional[str] = None


# ── Description template ────────────────────────────────────────────────────

def _build_description(description: str, topic: str) -> str:
    """
    Inject CTA, channel credit, and hashtags into the raw LLM description.
    """
    hashtags = (
        "#psychology #psychologyfacts #mindset #mentalhealth "
        "#brainscience #shorts #youtubeshorts"
    )
    return (
        f"{description}\n\n"
        f"🧠 {CTA_TEXT} — {CHANNEL_NAME}\n\n"
        f"Topic: {topic}\n\n"
        f"{hashtags}"
    )


def _build_tags(script_tags: list[str]) -> list[str]:
    """Merge script-specific tags with channel defaults, deduped, max 500 chars."""
    combined = list(dict.fromkeys(script_tags + YT_DEFAULT_TAGS))
    # YouTube enforces 500-char total tag budget
    result, budget = [], 500
    for tag in combined:
        if len(tag) + 1 <= budget:
            result.append(tag)
            budget -= len(tag) + 1   # +1 for comma separator
    return result


# ── Uploader ────────────────────────────────────────────────────────────────

class YouTubeUploader:
    """
    Uploads rendered video files to YouTube with full metadata.

    Parameters
    ----------
    db : Shared Database instance.
    """

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db      = db or Database()
        self._auth    = YouTubeAuthManager(db=self._db)
        self._tracker = QuotaTracker(db=self._db)
        self._db.init()

    # ── Public ─────────────────────────────────────────────────────────────

    def upload_short(
        self,
        video_path:   Path,
        video_id:     str,
        title:        str,
        description:  str,
        tags:         list[str],
        topic:        str,
        privacy:      str = "public",
    ) -> UploadResult:
        """
        Upload one Short to YouTube.

        Automatically selects the first non-exhausted OAuth client.
        On HTTP 403 quotaExceeded, invalidates that client and retries
        with the next one.  On all other errors, retries with backoff.

        Parameters
        ----------
        video_path  : Local path to the rendered .mp4 file.
        video_id    : Internal DB UUID for the videos table.
        title       : YouTube title (max 100 chars).
        description : Raw LLM description (will be templated here).
        tags        : Script-specific tag list.
        topic       : Broad psychology topic (injected into description).
        privacy     : 'public' | 'unlisted' | 'private'.

        Returns
        -------
        UploadResult with youtube_video_id on success.
        """
        return self._upload(
            video_path=video_path,
            video_id=video_id,
            title=title[:100],
            description=_build_description(description, topic),
            tags=_build_tags(tags),
            topic=topic,
            privacy=privacy,
            is_short=True,
        )

    def upload_compilation(
        self,
        video_path:  Path,
        video_id:    str,
        title:       str,
        description: str,
        tags:        list[str],
        topic:       str = "weekly psychology compilation",
        privacy:     str = "public",
    ) -> UploadResult:
        """Upload a weekly long-form compilation video."""
        return self._upload(
            video_path=video_path,
            video_id=video_id,
            title=title[:100],
            description=_build_description(description, topic),
            tags=_build_tags(tags),
            topic=topic,
            privacy=privacy,
            is_short=False,
        )

    # ── Core upload logic ───────────────────────────────────────────────────

    def _upload(
        self,
        video_path:  Path,
        video_id:    str,
        title:       str,
        description: str,
        tags:        list[str],
        topic:       str,
        privacy:     str,
        is_short:    bool,
    ) -> UploadResult:
        """
        Inner upload loop with client rotation on quota exhaustion.
        Tries each non-exhausted client in turn.
        """
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Append #Shorts to title for Shorts (helps YouTube classify them)
        final_title = f"{title} #Shorts" if is_short and "#Shorts" not in title else title

        body = {
            "snippet": {
                "title":       final_title,
                "description": description,
                "tags":        tags,
                "categoryId":  YT_CATEGORY_ID,
                "defaultLanguage": "en",
            },
            "status": {
                "privacyStatus":           privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        # Try each client; rotate on quota errors
        tried_clients: list[int] = []

        for attempt in range(len(self._auth._clients)):
            try:
                client_index = self._auth.get_active_client_index()
            except QuotaExhaustedError:
                logger.error("All YouTube clients exhausted — aborting upload.")
                result = UploadResult(
                    success=False,
                    client_index=0,
                    error_message="All OAuth clients quota-exhausted.",
                )
                self._db.insert_upload(
                    video_id=video_id,
                    title=final_title,
                    yt_client_index=0,
                    upload_status="quota_exceeded",
                    error_message=result.error_message,
                )
                return result

            if client_index in tried_clients:
                break
            tried_clients.append(client_index)

            logger.info(
                "Upload: starting — client=%d file=%s title='%s'",
                client_index, video_path.name, final_title,
            )

            try:
                service = self._auth.get_service(client_index)
                yt_video_id = self._resumable_upload(service, body, video_path)

                yt_url = f"https://www.youtube.com/watch?v={yt_video_id}"

                # Accounting
                self._tracker.record_upload(client_index)
                self._db.mark_video_uploaded(video_id)
                self._db.insert_upload(
                    video_id=video_id,
                    title=final_title,
                    yt_client_index=client_index,
                    youtube_video_id=yt_video_id,
                    youtube_url=yt_url,
                    privacy_status=privacy,
                    upload_status="success",
                    http_status_code=200,
                )

                logger.info(
                    "Upload SUCCESS: yt_id=%s url=%s client=%d",
                    yt_video_id, yt_url, client_index,
                )
                return UploadResult(
                    success=True,
                    youtube_video_id=yt_video_id,
                    youtube_url=yt_url,
                    client_index=client_index,
                )

            except HttpError as exc:
                status_code = int(exc.status)
                reason = _extract_reason(exc)

                if status_code == 403 and "quotaExceeded" in reason:
                    logger.warning(
                        "Upload: quota exceeded on client %d — rotating …",
                        client_index,
                    )
                    self._auth.invalidate_client(client_index)
                    continue   # try next client

                # Non-quota HTTP error — log and fail
                error_msg = f"HTTP {status_code}: {reason}"
                logger.error("Upload FAILED: %s", error_msg)
                self._db.insert_upload(
                    video_id=video_id,
                    title=final_title,
                    yt_client_index=client_index,
                    upload_status="failed",
                    http_status_code=status_code,
                    error_message=error_msg,
                )
                return UploadResult(
                    success=False,
                    client_index=client_index,
                    error_message=error_msg,
                )

            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                logger.error("Upload FAILED (unexpected): %s", error_msg)
                self._db.insert_upload(
                    video_id=video_id,
                    title=final_title,
                    yt_client_index=client_index,
                    upload_status="failed",
                    error_message=error_msg,
                )
                return UploadResult(
                    success=False,
                    client_index=client_index,
                    error_message=error_msg,
                )

        # All rotation attempts exhausted
        result = UploadResult(
            success=False,
            client_index=0,
            error_message="Upload failed after trying all available clients.",
        )
        return result

    # ── Resumable upload ────────────────────────────────────────────────────

    @with_retry(max_attempts=5, wait_min=5.0, wait_max=60.0, multiplier=2.0)
    def _resumable_upload(self, service, body: dict, video_path: Path) -> str:
        """
        Execute a resumable media upload and return the YouTube video ID.

        Uses exponential backoff on transient server errors (5xx) as
        recommended in the YouTube API documentation.

        Returns
        -------
        YouTube video ID string.

        Raises
        ------
        HttpError : On terminal API errors (4xx except those handled above).
        RuntimeError : If the upload response contains no video ID.
        """
        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            chunksize=_CHUNK_SIZE,
            resumable=True,
        )

        request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        retry_count = 0

        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    logger.debug("Upload progress: %d%%", pct)
            except HttpError as exc:
                if int(exc.status) in _RETRYABLE_STATUS:
                    retry_count += 1
                    if retry_count > _MAX_RESUMABLE_RETRIES:
                        raise
                    wait = min(2 ** retry_count + random.uniform(0, 1), 60)
                    logger.warning(
                        "Resumable upload: HTTP %s — retry %d/%d in %.1fs",
                        exc.status, retry_count, _MAX_RESUMABLE_RETRIES, wait,
                    )
                    time.sleep(wait)
                else:
                    raise
            except _RETRYABLE_EXCEPTIONS as exc:
                retry_count += 1
                if retry_count > _MAX_RESUMABLE_RETRIES:
                    raise
                wait = min(2 ** retry_count + random.uniform(0, 1), 60)
                logger.warning(
                    "Resumable upload: network error (%s) — retry %d/%d in %.1fs",
                    type(exc).__name__, retry_count, _MAX_RESUMABLE_RETRIES, wait,
                )
                time.sleep(wait)

        if response is None or "id" not in response:
            raise RuntimeError(
                f"YouTube API returned no video ID. Full response: {response}"
            )

        return response["id"]


# ── Helpers ─────────────────────────────────────────────────────────────────

def _extract_reason(exc: HttpError) -> str:
    """Pull the reason string from a googleapiclient HttpError."""
    try:
        import json as _json
        content = _json.loads(exc.content.decode("utf-8"))
        return content.get("error", {}).get("errors", [{}])[0].get("reason", str(exc))
    except Exception:
        return str(exc)
