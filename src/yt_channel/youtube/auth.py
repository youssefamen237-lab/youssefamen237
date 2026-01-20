from __future__ import annotations

import logging
from typing import Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

ANALYTICS_SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def make_credentials(*, client_id: str, client_secret: str, refresh_token: str, scopes: list[str]) -> Credentials:
    if not (client_id and client_secret and refresh_token):
        raise ValueError("YouTube OAuth credentials missing. Provide YT_CLIENT_ID/YT_CLIENT_SECRET/YT_REFRESH_TOKEN.")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
    )
    creds.refresh(Request())
    return creds


def build_youtube_service(*, client_id: str, client_secret: str, refresh_token: str):
    creds = make_credentials(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        scopes=YOUTUBE_SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def build_analytics_service(*, client_id: str, client_secret: str, refresh_token: str):
    creds = make_credentials(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        scopes=YOUTUBE_SCOPES + ANALYTICS_SCOPES,
    )
    return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
