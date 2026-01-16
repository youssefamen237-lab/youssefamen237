from __future__ import annotations

import random
import time
from datetime import datetime
from typing import Any

from ytquiz.log import Log
from ytquiz.utils import rfc3339


def upload_video(
    *,
    youtube: Any,
    file_path: str,
    title: str,
    description: str,
    tags: list[str],
    category_id: str,
    privacy_status: str,
    publish_at: datetime | None,
    made_for_kids: bool,
    log: Log,
) -> str:
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError

    body: dict[str, Any] = {
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
        },
    }

    if publish_at is not None:
        body["status"]["publishAt"] = rfc3339(publish_at)

    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)

    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    last_err = None
    for attempt in range(5):
        try:
            resp = None
            while resp is None:
                status, resp = req.next_chunk()
                _ = status
            video_id = str(resp.get("id"))
            if not video_id:
                raise RuntimeError(f"No video id in response: {resp}")
            log.info(f"Uploaded video id={video_id}")
            return video_id
        except HttpError as e:
            last_err = e
            wait = 2 ** attempt + random.random()
            log.warn(f"Upload HttpError (attempt {attempt+1}/5): {e}. Waiting {wait:.1f}s")
            time.sleep(wait)
        except Exception as e:
            last_err = e
            wait = 2 ** attempt + random.random()
            log.warn(f"Upload error (attempt {attempt+1}/5): {e}. Waiting {wait:.1f}s")
            time.sleep(wait)

    raise RuntimeError(f"Upload failed: {last_err}")


def set_thumbnail(*, youtube: Any, video_id: str, thumbnail_path: str, log: Log) -> None:
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError

    media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
    req = youtube.thumbnails().set(videoId=video_id, media_body=media)

    last_err = None
    for attempt in range(5):
        try:
            req.execute()
            log.info(f"Thumbnail set for {video_id}")
            return
        except HttpError as e:
            last_err = e
            wait = 2 ** attempt + random.random()
            log.warn(f"Thumbnail HttpError (attempt {attempt+1}/5): {e}. Waiting {wait:.1f}s")
            time.sleep(wait)
        except Exception as e:
            last_err = e
            wait = 2 ** attempt + random.random()
            log.warn(f"Thumbnail error (attempt {attempt+1}/5): {e}. Waiting {wait:.1f}s")
            time.sleep(wait)

    raise RuntimeError(f"Thumbnail failed: {last_err}")
