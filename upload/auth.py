"""
upload/auth.py
==============
YouTube OAuth2 credential manager with automatic rotation across
up to 3 Google Cloud project client secrets.
"""

import base64
import json
import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config.api_keys import YouTubeClient, get_youtube_clients
from database.db import Database
from utils.logger import get_logger

logger = get_logger(__name__)

_SCOPES: list[str] = ["https://www.googleapis.com/auth/youtube.upload"]
_API_SERVICE  = "youtube"
_API_VERSION  = "v3"
UPLOAD_COST_UNITS: int = 1_600

class QuotaExhaustedError(RuntimeError):
    pass

class YouTubeAuthManager:
    def __init__(self, db: Optional[Database] = None) -> None:
        self._db      = db or Database()
        self._clients = get_youtube_clients()
        self._db.init()

        for client in self._clients:
            self._hydrate_ci_token(client)

    def get_service(self, client_index: Optional[int] = None):
        if client_index is not None:
            client = self._get_client_by_index(client_index)
            creds  = self._get_or_refresh_credentials(client)
            return build(_API_SERVICE, _API_VERSION, credentials=creds)

        for client in self._clients:
            if self._db.is_quota_safe(client.index, UPLOAD_COST_UNITS):
                logger.info("Auth: using client %d (%s)", client.index, client.label)
                creds = self._get_or_refresh_credentials(client)
                return build(_API_SERVICE, _API_VERSION, credentials=creds)

        raise QuotaExhaustedError("All YouTube OAuth clients have exhausted their daily quota.")

    def get_active_client_index(self) -> int:
        for client in self._clients:
            if self._db.is_quota_safe(client.index, UPLOAD_COST_UNITS):
                return client.index
        raise QuotaExhaustedError("All YouTube clients exhausted.")

    def invalidate_client(self, client_index: int) -> None:
        logger.warning("Auth: marking client %d as quota-exhausted.", client_index)
        self._db.log_quota_usage(yt_client_index=client_index, units_used=10_000)

    def _get_or_refresh_credentials(self, client: YouTubeClient) -> Credentials:
        creds: Optional[Credentials] = None
        token_path = Path(client.token_path)

        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
            except Exception as exc:
                logger.warning("Auth: failed to load token for client %d (%s).", client.index, exc)
                creds = None

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_token(creds, token_path)
            except Exception as exc:
                logger.warning("Auth: token refresh failed for client %d (%s).", client.index, exc)
                creds = None

        if not creds or not creds.valid:
            secret_env = os.getenv(f"YT_CLIENT_SECRET_{client.index}", "").strip()
            secret_path = Path(f"client_secret_{client.index}.json")
            
            if secret_env.startswith("{"):
                secret_path.write_text(secret_env, encoding="utf-8")
            elif not secret_path.exists() and Path(client.client_secret).exists():
                secret_path = Path(client.client_secret)
                
            if not secret_path.exists():
                raise FileNotFoundError(
                    f"Client secret not found for client {client.index}. "
                    f"Ensure YT_CLIENT_SECRET_{client.index} is set in GitHub Secrets."
                )
                
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), _SCOPES)
            creds = flow.run_local_server(port=0)
            self._save_token(creds, token_path)

        return creds

    def _get_client_by_index(self, index: int) -> YouTubeClient:
        for c in self._clients:
            if c.index == index:
                return c
        raise ValueError(f"YouTube client index {index} is not configured.")

    @staticmethod
    def _save_token(creds: Credentials, token_path: Path) -> None:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    @staticmethod
    def _hydrate_ci_token(client: YouTubeClient) -> None:
        env_var = f"YT_TOKEN_JSON_{client.index}"
        token_val = os.getenv(env_var, "").strip()
        if not token_val:
            return

        token_path = Path(client.token_path)
        if token_path.exists():
            return

        try:
            if token_val.startswith("{"):
                token_json = token_val
            else:
                token_json = base64.b64decode(token_val).decode("utf-8")
            
            json.loads(token_json)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(token_json, encoding="utf-8")
        except Exception as exc:
            logger.error("Auth: failed to hydrate CI token for client %d: %s", client.index, exc)
