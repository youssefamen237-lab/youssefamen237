from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from ..config import YouTubeAuthProfile

log = logging.getLogger(__name__)

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
TOKEN_URI = "https://oauth2.googleapis.com/token"


@dataclass(frozen=True)
class AuthContext:
    profile_index: int
    credentials: Credentials


def get_authenticated_service(profiles: Sequence[YouTubeAuthProfile]):
    last_err: Exception | None = None
    for i, p in enumerate(profiles):
        try:
            creds = Credentials(
                token=None,
                refresh_token=p.refresh_token,
                token_uri=TOKEN_URI,
                client_id=p.client_id,
                client_secret=p.client_secret,
                scopes=[YOUTUBE_UPLOAD_SCOPE],
            )
            creds.refresh(Request())
            service = build("youtube", "v3", credentials=creds, cache_discovery=False)
            return AuthContext(profile_index=i, credentials=creds), service
        except Exception as e:
            last_err = e
            log.warning("YouTube auth profile %d failed: %s", i + 1, str(e))
    raise RuntimeError(f"No working YouTube OAuth profile. Last error: {last_err}")
