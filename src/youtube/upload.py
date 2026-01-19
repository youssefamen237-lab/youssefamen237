from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from ..utils.retry import retry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class UploadResult:
    video_id: str
    kind: str
    privacy_status: str
    publish_at: Optional[str]


def _is_retriable_http_error(err: Exception) -> bool:
    if not isinstance(err, HttpError):
        return False
    try:
        status = int(err.resp.status)
    except Exception:
        return False
    return status in {429, 500, 502, 503, 504}


def upload_video(
    youtube,
    *,
    file_path: str,
    title: str,
    description: str,
    tags: list[str],
    category_id: str,
    privacy_status: str,
    publish_at_iso: Optional[str],
    notify_subscribers: bool,
    made_for_kids: bool = False,
    contains_synthetic_media: bool = True,
) -> UploadResult:
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": bool(made_for_kids),
            "containsSyntheticMedia": bool(contains_synthetic_media),
        },
    }
    if publish_at_iso:
        body["status"]["publishAt"] = publish_at_iso

    media = MediaFileUpload(file_path, mimetype="video/*", resumable=True)

    def _do_upload() -> UploadResult:
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
            notifySubscribers=bool(notify_subscribers),
        )
        response = None
        last_progress = -1
        while response is None:
            status, response = request.next_chunk()
            if status is not None:
                pct = int(status.progress() * 100)
                if pct != last_progress:
                    last_progress = pct
                    log.info("Upload progress: %d%%", pct)
            time.sleep(0.5)

        video_id = response.get("id")
        if not isinstance(video_id, str) or not video_id:
            raise RuntimeError(f"Upload did not return video id: {response}")
        return UploadResult(
            video_id=video_id,
            kind=str(response.get("kind", "")),
            privacy_status=privacy_status,
            publish_at=publish_at_iso,
        )

    return retry(_do_upload, tries=5, base_delay_s=2.0, max_delay_s=30.0, retry_if=_is_retriable_http_error)


def set_thumbnail(youtube, *, video_id: str, thumbnail_path: str) -> None:
    media = MediaFileUpload(thumbnail_path, mimetype="image/png", resumable=False)

    def _call() -> None:
        youtube.thumbnails().set(videoId=video_id, media_body=media).execute()

    retry(_call, tries=4, base_delay_s=2.0, max_delay_s=25.0, retry_if=_is_retriable_http_error)
