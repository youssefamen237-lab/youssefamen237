\
import logging
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .youtube_auth import OAuthCandidate, pick_working_credentials

logger = logging.getLogger(__name__)


UPLOAD_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def _is_retryable_http_error(e: HttpError) -> bool:
    try:
        status = int(getattr(e.resp, "status", 0))
    except Exception:
        status = 0
    return status in {429, 500, 502, 503, 504}


def _resumable_upload(request, max_retries: int = 8) -> Dict[str, Any]:
    response = None
    error = None
    retry = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if response is not None:
                return response
        except HttpError as e:
            if _is_retryable_http_error(e):
                error = e
            else:
                raise
        except Exception as e:
            error = e

        if error is not None:
            retry += 1
            if retry > max_retries:
                raise RuntimeError(f"Upload failed after retries: {error}") from error
            sleep = (2 ** retry) + random.random()
            logger.warning("Retrying upload in %.2fs due to error: %s", sleep, error)
            time.sleep(sleep)
            error = None
    return response  # type: ignore


def upload_video(
    *,
    oauth_candidates: List[OAuthCandidate],
    video_path: Path,
    title: str,
    description: str,
    tags: Optional[List[str]],
    category_id: str,
    privacy_status: str,
    made_for_kids: bool,
    thumbnail_path: Optional[Path] = None,
) -> str:
    creds = pick_working_credentials(oauth_candidates, scopes=UPLOAD_SCOPES)
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": str(category_id),
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": bool(made_for_kids),
        },
    }
    if tags:
        body["snippet"]["tags"] = tags

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/*")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    resp = _resumable_upload(request)
    video_id = str(resp.get("id"))
    if not video_id:
        raise RuntimeError(f"Upload succeeded but no video id returned: {resp}")

    if thumbnail_path and thumbnail_path.exists():
        try:
            youtube.thumbnails().set(videoId=video_id, media_body=str(thumbnail_path)).execute()
        except Exception as e:
            logger.warning("Failed to set thumbnail for %s: %s", video_id, e)

    return video_id
