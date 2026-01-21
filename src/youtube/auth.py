from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

log = logging.getLogger("yt_auth")

TOKEN_URI = "https://oauth2.googleapis.com/token"


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _build(client_id: str, client_secret: str, refresh_token: str, scopes: List[str]) -> Credentials:
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
    )
    creds.refresh(Request())
    return creds


def get_credentials(scopes: List[str]) -> Credentials:
    candidates: List[Tuple[str, str, str]] = [
        (_env("YT_CLIENT_ID_1"), _env("YT_CLIENT_SECRET_1"), _env("YT_REFRESH_TOKEN_1")),
        (_env("YT_CLIENT_ID_2"), _env("YT_CLIENT_SECRET_2"), _env("YT_REFRESH_TOKEN_2")),
    ]
    last_err: Optional[Exception] = None
    for cid, csec, rt in candidates:
        if not cid or not csec or not rt:
            continue
        try:
            return _build(cid, csec, rt, scopes)
        except Exception as e:
            last_err = e
            log.warning("OAuth refresh failed for a credential set: %s", e)
            continue
    raise RuntimeError(f"Failed to obtain credentials for scopes={scopes}. Last error: {last_err}")
