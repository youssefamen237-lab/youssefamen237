"""
upload/auth.py
==============
YouTube OAuth2 credential manager.
Adapted to read direct credentials (ID, Secret, Refresh Token) from
environment variables, bypassing complex JSON file parsing.
"""

import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config.api_keys import YouTubeClient, get_youtube_clients
from database.db import Database
from utils.logger import get_logger

logger = get_logger(__name__)

# Scopes required for video upload + management
_SCOPES: list[str] = ["https://www.googleapis.com/auth/youtube.upload"]

# YouTube API service name and version
_API_SERVICE  = "youtube"
_API_VERSION  = "v3"

# Units consumed by a single video insert call
UPLOAD_COST_UNITS: int = 1_600


class QuotaExhaustedError(RuntimeError):
    """Raised when every configured YouTube client has hit its daily quota."""
    pass


class YouTubeAuthManager:
    """
    Manages OAuth2 credentials for all configured YouTube clients and
    selects the best available (non-exhausted) client for each upload.
    """

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db      = db or Database()
        self._clients = get_youtube_clients()
        self._db.init()

    # ── Public ─────────────────────────────────────────────────────────────

    def get_service(self, client_index: Optional[int] = None):
        """
        Return an authenticated YouTube API service object.
        """
        if client_index is not None:
            client = self._get_client_by_index(client_index)
            creds  = self._get_or_refresh_credentials(client)
            return build(_API_SERVICE, _API_VERSION, credentials=creds)

        # Auto-rotate: find the first client with sufficient quota
        for client in self._clients:
            if self._db.is_quota_safe(client.index, UPLOAD_COST_UNITS):
                logger.info(
                    "Auth: using client %d (%s)", client.index, client.label
                )
                creds = self._get_or_refresh_credentials(client)
                return build(_API_SERVICE, _API_VERSION, credentials=creds)

        raise QuotaExhaustedError(
            "All YouTube OAuth clients have exhausted their daily quota. "
            "Uploads will resume automatically at midnight UTC."
        )

    def get_active_client_index(self) -> int:
        """
        Return the index of the first non-exhausted client.
        """
        for client in self._clients:
            if self._db.is_quota_safe(client.index, UPLOAD_COST_UNITS):
                return client.index
        raise QuotaExhaustedError("All YouTube clients exhausted.")

    def invalidate_client(self, client_index: int) -> None:
        """
        Mark a client as exhausted by logging 10 000 units for today.
        """
        logger.warning(
            "Auth: marking client %d as quota-exhausted.", client_index
        )
        self._db.log_quota_usage(
            yt_client_index=client_index,
            units_used=10_000,   # saturate the daily limit
        )

    # ── Credential management ───────────────────────────────────────────────

    def _get_or_refresh_credentials(self, client: YouTubeClient) -> Credentials:
        """
        Reads YouTube ID, Secret, and Refresh Token directly from Environment Variables.
        """
        client_id = os.getenv(f"YT_CLIENT_ID_{client.index}")
        client_secret = os.getenv(f"YT_CLIENT_SECRET_{client.index}")
        refresh_token = os.getenv(f"YT_REFRESH_TOKEN_{client.index}")

        if not all([client_id, client_secret, refresh_token]):
            raise FileNotFoundError(
                f"Missing credentials for client {client.index}. "
                f"Ensure YT_CLIENT_ID_{client.index}, YT_CLIENT_SECRET_{client.index}, "
                f"and YT_REFRESH_TOKEN_{client.index} are mapped in the workflow YAML."
            )

        # Create Credentials object directly bypassing JSON files
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret
        )

        # Refresh if expired (often happens automatically on first request)
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info(
                    "Auth: refreshed token for client %d.", client.index
                )
            except Exception as exc:
                logger.warning(
                    "Auth: token refresh failed for client %d (%s). ", 
                    client.index, exc
                )

        return creds

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _get_client_by_index(self, index: int) -> YouTubeClient:
        for c in self._clients:
            if c.index == index:
                return c
        raise ValueError(
            f"YouTube client index {index} is not configured."
        )

    @staticmethod
    def _save_token(creds: Credentials, token_path: Path) -> None:
        pass

    @staticmethod
    def _hydrate_ci_token(client: YouTubeClient) -> None:
        pass
