\
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from autoyt.pipeline.youtube.auth import get_credentials
from autoyt.utils.logging_utils import get_logger
from autoyt.utils.time import isoformat_rfc3339
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

log = get_logger("autoyt.youtube")


SCOPES_UPLOAD = ["https://www.googleapis.com/auth/youtube.upload"]
SCOPES_READONLY = ["https://www.googleapis.com/auth/youtube.readonly"]


@dataclass
class UploadResult:
    video_id: str
    upload_response: Dict[str, Any]


def _build_youtube(profile: int, scopes: List[str]):
    creds = get_credentials(profile, scopes=scopes)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type(HttpError),
)
def upload_video(
    oauth_profile: int,
    file_path: Path,
    title: str,
    description: str,
    tags: List[str],
    category_id: str,
    publish_at_utc: Optional[dt.datetime],
    made_for_kids: bool,
    default_language: str = "en",
    notify_subscribers: bool = False,
) -> UploadResult:
    youtube = _build_youtube(oauth_profile, scopes=SCOPES_UPLOAD)

    snippet = {
        "title": title[:95],  # hard cap to be safe
        "description": description,
        "tags": tags[:30],
        "categoryId": category_id,
        "defaultLanguage": default_language,
        "defaultAudioLanguage": default_language,
    }

    status: Dict[str, Any] = {"selfDeclaredMadeForKids": bool(made_for_kids)}
    if publish_at_utc:
        # YouTube requires 'private' for scheduling
        status["privacyStatus"] = "private"
        status["publishAt"] = isoformat_rfc3339(publish_at_utc)
    else:
        status["privacyStatus"] = "public"

    body = {"snippet": snippet, "status": status}

    media = MediaFileUpload(str(file_path), chunksize=-1, resumable=True)

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
        notifySubscribers=notify_subscribers,
    )

    response = None
    try:
        response = request.execute()
    except HttpError as e:
        log.error(f"YouTube upload failed: {e}")
        raise

    vid = response.get("id", "")
    if not vid:
        raise RuntimeError("YouTube API did not return video id")

    return UploadResult(video_id=vid, upload_response=response)
