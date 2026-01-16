from __future__ import annotations

from typing import Any

from ytquiz.config import Config
from ytquiz.log import Log


def build_credentials(cfg: Config, log: Log):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    last_err = None
    for client in cfg.oauth_clients:
        try:
            # IMPORTANT:
            # Do NOT pass scopes during refresh. Passing scopes that are not part of the original
            # refresh token grant causes: invalid_scope.
            creds = Credentials(
                token=None,
                refresh_token=client.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client.client_id,
                client_secret=client.client_secret,
                scopes=None,
            )
            creds.refresh(Request())
            if not creds.valid:
                raise RuntimeError("Credentials not valid after refresh")
            return creds
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError(f"OAuth credentials failed: {last_err}")


def build_youtube_services(cfg: Config, log: Log) -> dict[str, Any]:
    from googleapiclient.discovery import build

    creds = build_credentials(cfg, log)

    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    analytics = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

    return {"youtube": youtube, "analytics": analytics, "creds": creds}
