from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .auth import get_credentials
from ..utils.retry import retry

log = logging.getLogger("yt_uploader")

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def _iso_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_youtube_client():
    creds = get_credentials([YOUTUBE_UPLOAD_SCOPE])
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload_video(
    *,
    video_path: str | Path,
    metadata: Dict[str, Any],
    publish_at: Optional[datetime],
    privacy_status: str,
    notify_subscribers: bool,
    made_for_kids: bool,
    contains_synthetic_media: bool,
) -> str:
    youtube = build_youtube_client()
    video_path = Path(video_path)

    snippet = {
        "title": metadata["title"],
        "description": metadata["description"],
        "tags": metadata.get("tags", []),
        "categoryId": metadata.get("categoryId", "24"),
        "defaultLanguage": "en",
    }
    status: Dict[str, Any] = {
        "privacyStatus": privacy_status,
        "selfDeclaredMadeForKids": bool(made_for_kids),
    }
    if contains_synthetic_media:
        status["containsSyntheticMedia"] = True

    if publish_at is not None:
        status["privacyStatus"] = "private"
        status["publishAt"] = _iso_rfc3339(publish_at)

    body = {"snippet": snippet, "status": status}

    media = MediaFileUpload(str(video_path), mimetype="video/*", resumable=True)

    def _do_upload() -> str:
        req = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
            notifySubscribers=bool(notify_subscribers),
        )
        resp = req.execute()
        vid = resp.get("id")
        if not vid:
            raise RuntimeError(f"Upload response missing video id: {resp}")
        return str(vid)

    vid = retry(_do_upload, attempts=4, base_delay=2.0, max_delay=60.0)
    log.info("Uploaded video id=%s", vid)
    return vid


def set_thumbnail(video_id: str, thumbnail_path: str | Path) -> None:
    youtube = build_youtube_client()
    thumbnail_path = Path(thumbnail_path)
    media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg", resumable=False)

    def _do() -> None:
        youtube.thumbnails().set(videoId=video_id, media_body=media).execute()

    retry(_do, attempts=3, base_delay=2.0, max_delay=30.0)
