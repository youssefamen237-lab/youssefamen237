\
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


@dataclass
class OAuthProfile:
    client_id: str
    client_secret: str
    refresh_token: str


def load_oauth_profile(profile_num: int) -> OAuthProfile:
    cid = os.environ.get(f"YT_CLIENT_ID_{profile_num}", "")
    csec = os.environ.get(f"YT_CLIENT_SECRET_{profile_num}", "")
    rt = os.environ.get(f"YT_REFRESH_TOKEN_{profile_num}", "")
    if not cid or not csec or not rt:
        raise RuntimeError(f"Missing YouTube OAuth secrets for profile {profile_num}")
    return OAuthProfile(client_id=cid, client_secret=csec, refresh_token=rt)


def get_credentials(profile_num: int, scopes: List[str]) -> Credentials:
    prof = load_oauth_profile(profile_num)
    creds = Credentials(
        token=None,
        refresh_token=prof.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=prof.client_id,
        client_secret=prof.client_secret,
        scopes=scopes,
    )
    creds.refresh(Request())
    return creds
