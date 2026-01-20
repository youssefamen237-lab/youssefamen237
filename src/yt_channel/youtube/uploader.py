from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UploadResult:
    video_id: str
    privacy_status: str


class YouTubeUploader:
    def __init__(self, *, service, rng: random.Random) -> None:
        self.service = service
        self.rng = rng

    def _execute_with_backoff(self, req, max_retries: int = 6):
        for attempt in range(max_retries):
            try:
                return req.execute()
            except HttpError as e:
                status = getattr(e.resp, "status", None)
                if status in (429, 500, 503):
                    sleep = min(2 ** attempt + self.rng.random(), 60)
                    logger.warning("YouTube API error %s, backing off %.1fs", status, sleep)
                    time.sleep(sleep)
                    continue
                raise
        raise RuntimeError("YouTube API request failed after retries")

    def upload_video(
        self,
        *,
        video_path: Path,
        title: str,
        description: str,
        tags: List[str],
        category_id: str,
        privacy_status: str,
        publish_at: Optional[str] = None,
        thumbnail_path: Optional[Path] = None,
        is_made_for_kids: bool = False,
    ) -> UploadResult:
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": bool(is_made_for_kids),
            },
        }
        if publish_at:
            body["status"]["publishAt"] = publish_at

        media = MediaFileUpload(str(video_path), chunksize=1024 * 1024 * 8, resumable=True)
        req = self.service.videos().insert(part="snippet,status", body=body, media_body=media, notifySubscribers=False)

        # Resumable upload
        response = None
        for attempt in range(10):
            try:
                status, response = req.next_chunk()
                if response and "id" in response:
                    break
            except HttpError as e:
                status_code = getattr(e.resp, "status", None)
                if status_code in (429, 500, 503):
                    sleep = min(2 ** attempt + self.rng.random(), 60)
                    logger.warning("Upload chunk error %s, retry in %.1fs", status_code, sleep)
                    time.sleep(sleep)
                    continue
                raise

        if not response or "id" not in response:
            raise RuntimeError("Video upload failed: no id in response")

        video_id = response["id"]

        if thumbnail_path:
            try:
                th_media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg", resumable=False)
                th_req = self.service.thumbnails().set(videoId=video_id, media_body=th_media)
                self._execute_with_backoff(th_req)
            except Exception as e:
                logger.warning("Thumbnail upload failed for %s: %s", video_id, e)

        return UploadResult(video_id=video_id, privacy_status=privacy_status)
