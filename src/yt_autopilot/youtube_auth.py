\
import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)


TOKEN_URI = "https://oauth2.googleapis.com/token"


def build_credentials(client_id: str, client_secret: str, refresh_token: str, scopes: List[str]) -> Credentials:
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


@dataclass
class OAuthCandidate:
    client_id: str
    client_secret: str
    refresh_token: str


def pick_working_credentials(candidates: List[OAuthCandidate], scopes: List[str]) -> Credentials:
    last_err: Optional[Exception] = None
    for c in candidates:
        try:
            creds = build_credentials(c.client_id, c.client_secret, c.refresh_token, scopes=scopes)
            return creds
        except Exception as e:
            last_err = e
            logger.warning("OAuth candidate failed: %s", e)
    raise RuntimeError(f"All OAuth candidates failed: {last_err}")
