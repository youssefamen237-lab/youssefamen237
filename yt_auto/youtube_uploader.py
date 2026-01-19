from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from yt_auto.config import YouTubeOAuth
from yt_auto.utils import RetryPolicy, backoff_sleep_s


@dataclass(frozen=True)
class UploadResult:
    video_id: str


class YouTubeUploader:
    def __init__(self, oauth_list: list[YouTubeOAuth]) -> None:
        if not oauth_list:
            raise RuntimeError("missing_youtube_oauth_credentials")
        self.oauth_list = oauth_list
        self._service_cache: dict[str, Any] = {}

    def _cache_key(self, oauth: YouTubeOAuth) -> str:
        raw = f"{oauth.client_id}|{oauth.refresh_token}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _parse_env_scopes(self) -> list[str]:
        raw = (os.getenv("YT_OAUTH_SCOPES", "") or "").strip()
        if not raw:
            return []
        scopes = [s.strip() for s in raw.split(",") if s.strip()]
        return scopes

    def _scope_candidates(self) -> list[list[str] | None]:
        env_scopes = self._parse_env_scopes()
        candidates: list[list[str] | None] = []
        if env_scopes:
            candidates.append(env_scopes)

        # Start with least-privileged common scopes first (best compatibility with existing refresh tokens)
        candidates.append(["https://www.googleapis.com/auth/youtube.upload"])
        candidates.append(["https://www.googleapis.com/auth/youtube.force-ssl"])
        candidates.append(["https://www.googleapis.com/auth/youtube"])

        # Final fallback: do not request scopes in refresh call (use scopes bound to refresh token)
        candidates.append(None)
        return candidates

    def _is_invalid_scope(self, e: RefreshError) -> bool:
        try:
            if len(e.args) > 1 and isinstance(e.args[1], dict):
                data = e.args[1]
                if str(data.get("error", "")).strip().lower() == "invalid_scope":
                    return True
            if "invalid_scope" in str(e).lower():
                return True
        except Exception:
            return False
        return False

    def _service_for(self, oauth: YouTubeOAuth):
        key = self._cache_key(oauth)
        if key in self._service_cache:
            return self._service_cache[key]

        last_err: Exception | None = None
        for scopes in self._scope_candidates():
            try:
                kwargs: dict[str, Any] = {
                    "token": None,
                    "refresh_token": oauth.refresh_token,
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "client_id": oauth.client_id,
                    "client_secret": oauth.client_secret,
                }
                if scopes is not None:
                    kwargs["scopes"] = scopes

                creds = Credentials(**kwargs)
                creds.refresh(Request())
                service = build("youtube", "v3", credentials=creds, cache_discovery=False)
                self._service_cache[key] = service
                return service
            except RefreshError as e:
                last_err = e
                if self._is_invalid_scope(e):
                    continue
                raise
            except Exception as e:
                last_err = e
                raise

        raise RuntimeError(f"youtube_oauth_refresh_failed: {last_err!r}")

    def upload_video(
        self,
        file_path: Path,
        title: str,
        description: str,
        tags: list[str],
        category_id: str,
        privacy_status: str,
        made_for_kids: bool,
        default_language: str = "en",
        default_audio_language: str = "en",
    ) -> UploadResult:
        policy = RetryPolicy(max_attempts=5, base_sleep_s=1.2, max_sleep_s=12.0)
        last_err: Exception | None = None

        for oauth in self.oauth_list:
            try:
                service = self._service_for(oauth)
            except Exception as e:
                last_err = e
                continue

            for attempt in range(1, policy.max_attempts + 1):
                try:
                    body: dict[str, Any] = {
                        "snippet": {
                            "title": title,
                            "description": description,
                            "tags": tags,
                            "categoryId": category_id,
                            "defaultLanguage": default_language,
                            "defaultAudioLanguage": default_audio_language,
                        },
                        "status": {
                            "privacyStatus": privacy_status,
                            "selfDeclaredMadeForKids": bool(made_for_kids),
                        },
                    }

                    media = MediaFileUpload(str(file_path), chunksize=-1, resumable=True)
                    req = service.videos().insert(part="snippet,status", body=body, media_body=media)

                    resp = None
                    while resp is None:
                        _status, resp = req.next_chunk()

                    vid = resp.get("id") if isinstance(resp, dict) else None
                    if not isinstance(vid, str) or not vid.strip():
                        raise RuntimeError("youtube_upload_missing_video_id")

                    return UploadResult(video_id=vid.strip())
                except HttpError as e:
                    last_err = e
                    time.sleep(backoff_sleep_s(attempt, policy))
                except Exception as e:
                    last_err = e
                    time.sleep(backoff_sleep_s(attempt, policy))

        raise RuntimeError(f"youtube_upload_failed: {last_err!r}")

    def set_thumbnail(self, video_id: str, thumbnail_path: Path) -> None:
        policy = RetryPolicy(max_attempts=4, base_sleep_s=1.0, max_sleep_s=10.0)
        last_err: Exception | None = None

        for oauth in self.oauth_list:
            try:
                service = self._service_for(oauth)
            except Exception as e:
                last_err = e
                continue

            for attempt in range(1, policy.max_attempts + 1):
                try:
                    media = MediaFileUpload(str(thumbnail_path))
                    req = service.thumbnails().set(videoId=video_id, media_body=media)
                    req.execute()
                    return
                except Exception as e:
                    last_err = e
                    time.sleep(backoff_sleep_s(attempt, policy))

        raise RuntimeError(f"youtube_set_thumbnail_failed: {last_err!r}")
