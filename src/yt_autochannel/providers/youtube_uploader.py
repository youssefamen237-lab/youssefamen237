from __future__ import annotations

import json
import random
import time
from datetime import datetime, timedelta

import pytz
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def _rfc3339(dt) -> str:
    # dt should be timezone-aware datetime
    s = dt.astimezone().isoformat()
    if s.endswith("+00:00"):
        s = s.replace("+00:00", "Z")
    return s


@dataclass
class UploadResult:
    video_id: str
    status: str


class YouTubeUploader:
    """YouTube Data API uploader using OAuth refresh token.

    Notes:
    - Scheduled publishing is supported via status.publishAt while privacyStatus is 'private'.
    - Retry/backoff is applied for 429/5xx and quota-ish 403 errors.
    """

    def __init__(self, channel_id: str, client_id: str, client_secret: str, refresh_token: str):
        if not client_id or not client_secret or not refresh_token:
            raise ValueError(
                "YouTube OAuth env vars are missing (YT_CLIENT_ID_1/YT_CLIENT_SECRET_1/YT_REFRESH_TOKEN_1)"
            )
        self.channel_id = channel_id or ""
        self.creds = Credentials(
            None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=YOUTUBE_SCOPES,
        )
        self._service = None

    @property
    def service(self):
        return self._get_service()

    def _get_service(self):
        if self._service is not None:
            return self._service
        self.creds.refresh(Request())
        self._service = build("youtube", "v3", credentials=self.creds, cache_discovery=False)
        return self._service

    def upload_video(
        self,
        video_file: Path,
        title: str,
        description: str,
        tags: List[str],
        publish_at_utc,
        is_short: bool,
        privacy_status: str = "private",
        is_for_kids: bool = False,
        category_id: Optional[str] = None,
    ) -> UploadResult:
        """Upload a video and schedule publishAt.

        - video_file: mp4 file path
        - publish_at_utc: timezone-aware datetime
        """
        service = self._get_service()

        publish_at = publish_at_utc
        if privacy_status == "private" and publish_at is not None:
            try:
                now = datetime.now(tz=pytz.UTC)
                if publish_at <= (now + timedelta(minutes=2)):
                    privacy_status = "public"
                    publish_at = None
            except Exception:
                pass


        # Trivia content fits Entertainment (24) or Education (27). Default 24.
        cat = category_id or ("24" if is_short else "24")

        body: Dict[str, Any] = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": cat,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": bool(is_for_kids),
            },
        }

        if privacy_status == "private" and publish_at is not None:
            body["status"]["publishAt"] = _rfc3339(publish_at)

        media = MediaFileUpload(str(video_file), chunksize=-1, resumable=True)
        request = service.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
        response = self._execute_with_backoff(request)
        video_id = str(response.get("id"))
        return UploadResult(video_id=video_id, status=str(body["status"]["privacyStatus"]))

    def set_thumbnail(self, video_id: str, thumbnail_file: Path) -> None:
        service = self._get_service()

        publish_at = publish_at_utc
        if privacy_status == "private" and publish_at is not None:
            try:
                now = datetime.now(tz=pytz.UTC)
                if publish_at <= (now + timedelta(minutes=2)):
                    privacy_status = "public"
                    publish_at = None
            except Exception:
                pass

        media = MediaFileUpload(str(thumbnail_file), mimetype="image/jpeg")
        request = service.thumbnails().set(videoId=video_id, media_body=media)
        self._execute_with_backoff(request)

    def get_basic_stats(self, video_id: str) -> Dict[str, Any]:
        service = self._get_service()

        publish_at = publish_at_utc
        if privacy_status == "private" and publish_at is not None:
            try:
                now = datetime.now(tz=pytz.UTC)
                if publish_at <= (now + timedelta(minutes=2)):
                    privacy_status = "public"
                    publish_at = None
            except Exception:
                pass

        request = service.videos().list(part="statistics", id=video_id)
        resp = self._execute_with_backoff(request)
        items = resp.get("items") or []
        if not items:
            return {}
        it = items[0]
        stats = it.get("statistics") or {}
        return {
            "video_id": video_id,
            "viewCount": int(stats.get("viewCount", 0)),
            "likeCount": int(stats.get("likeCount", 0)),
            "commentCount": int(stats.get("commentCount", 0)),
        }

    def _execute_with_backoff(self, request, max_attempts: int = 8):
        base = 1.5
        for attempt in range(1, max_attempts + 1):
            try:
                return request.execute()
            except HttpError as e:
                status = getattr(e, "status_code", None) or getattr(getattr(e, "resp", None), "status", None)
                retryable = status in (429, 500, 502, 503, 504)

                if status == 403:
                    try:
                        data = json.loads(e.content.decode("utf-8")) if hasattr(e, "content") else {}
                        reason = (((data.get("error") or {}).get("errors") or [{}])[0]).get("reason")
                        if reason in {"quotaExceeded", "userRateLimitExceeded", "rateLimitExceeded"}:
                            retryable = True
                    except Exception:
                        pass

                if not retryable or attempt == max_attempts:
                    raise

                sleep_s = min(60.0, (base ** attempt) + random.random())
                time.sleep(sleep_s)
            except Exception:
                if attempt == max_attempts:
                    raise
                time.sleep(min(30.0, (base ** attempt) + random.random()))
        raise RuntimeError("unreachable")
