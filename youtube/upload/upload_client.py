"""
youtube/upload/upload_client.py
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Dict, List, Optional
import requests, structlog
from youtube.upload.key_rotator import get_key_rotator
from youtube.upload.quota_manager import get_quota_manager, UNITS_PER_UPLOAD

logger = structlog.get_logger(__name__)

_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


@dataclass
class UploadResult:
    success:  bool
    video_id: Optional[str] = None
    key_used: Optional[int] = None
    error:    Optional[str] = None


class YouTubeUploadClient:

    def __init__(self) -> None:
        self._rotator = get_key_rotator()
        self._quota   = get_quota_manager()

    # ── Public API ────────────────────────────────────────────────────────────

    def upload_video(
        self,
        file_path:      str,
        title:          str,
        description:    str,
        tags:           List[str],
        category_id:    str = "28",          # Science & Technology
        privacy_status: str = "public",
        publish_at:     Optional[str] = None, # ISO 8601 UTC — sets status=private + scheduled
        is_short:       bool = True,
    ) -> UploadResult:
        try:
            key_index, _creds, access_token = self._rotator.select_upload_credentials()
        except RuntimeError as exc:
            logger.error("youtube_no_upload_capacity", error=str(exc))
            return UploadResult(False, error=str(exc))

        snippet: Dict = {
            "title":       title[:100],
            "description": description[:5000],
            "tags":        tags[:500],
            "categoryId":  category_id,
        }

        if is_short and "#shorts" not in snippet["description"].lower():
            snippet["description"] = (snippet["description"] + "\n\n#Shorts")[:5000]

        status: Dict = {
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
        }
        if publish_at:
            status["privacyStatus"] = "private"
            status["publishAt"]     = publish_at
        else:
            status["privacyStatus"] = privacy_status

        metadata = {"snippet": snippet, "status": status}

        try:
            video_id = self._resumable_upload(file_path, metadata, access_token)
        except RuntimeError as exc:
            err_str = str(exc)
            # 401 → token may have just expired despite cache; retry once with a forced refresh
            if "401" in err_str:
                try:
                    creds = self._rotator.get_credentials(key_index)
                    access_token = self._rotator.get_access_token(creds, force_refresh=True)
                    video_id = self._resumable_upload(file_path, metadata, access_token)
                except Exception as retry_exc:
                    logger.error("youtube_upload_retry_failed", key_index=key_index, error=str(retry_exc)[:200])
                    return UploadResult(False, key_used=key_index, error=str(retry_exc))
            else:
                logger.error("youtube_upload_failed", key_index=key_index, error=err_str[:200])
                return UploadResult(False, key_used=key_index, error=err_str)

        self._quota.record_upload(key_index, UNITS_PER_UPLOAD)
        logger.info(
            "youtube_upload_success",
            video_id=video_id, key_used=key_index, title=title[:50],
            scheduled=bool(publish_at),
        )
        return UploadResult(True, video_id=video_id, key_used=key_index)

    # ── Resumable upload protocol ────────────────────────────────────────────

    def _resumable_upload(self, file_path: str, metadata: Dict, access_token: str) -> str:
        file_size = os.path.getsize(file_path)
        if file_size <= 0:
            raise RuntimeError(f"Video file is empty: {file_path}")

        init_resp = requests.post(
            _UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(file_size),
            },
            json=metadata,
            timeout=30,
        )
        if init_resp.status_code != 200:
            raise RuntimeError(
                f"Upload session init failed (HTTP {init_resp.status_code}): {init_resp.text[:300]}"
            )

        session_uri = init_resp.headers.get("Location")
        if not session_uri:
            raise RuntimeError("YouTube did not return an upload session URI.")

        with open(file_path, "rb") as fh:
            put_resp = requests.put(
                session_uri,
                headers={
                    "Content-Type":   "video/mp4",
                    "Content-Length": str(file_size),
                },
                data=fh,
                timeout=900,
            )

        if put_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Upload PUT failed (HTTP {put_resp.status_code}): {put_resp.text[:300]}"
            )

        video_id = put_resp.json().get("id")
        if not video_id:
            raise RuntimeError(f"No video ID in YouTube response: {put_resp.text[:300]}")

        return video_id


_instance: Optional[YouTubeUploadClient] = None

def get_upload_client() -> YouTubeUploadClient:
    global _instance
    if _instance is None:
        _instance = YouTubeUploadClient()
    return _instance
