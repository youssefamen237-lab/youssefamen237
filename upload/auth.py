"""
upload/auth.py
==============
YouTube OAuth2 credential manager with automatic rotation across
up to 3 Google Cloud project client secrets.

Rotation strategy
-----------------
Clients are tried in index order (1 → 2 → 3).  A client is skipped
when quota_tracker reports it is exhausted for today.  If all clients
are exhausted, QuotaExhaustedError is raised so the pipeline can abort
gracefully rather than burning API units on doomed requests.

Token persistence
-----------------
OAuth tokens are cached as JSON files in .tokens/ (gitignored).
On first run per client the user must complete a browser authorisation
flow.  In GitHub Actions, pre-authorised token JSON files are stored
as base64-encoded Secrets and decoded at runtime — see README for setup.

GitHub Actions headless auth
-----------------------------
Set the env var YT_TOKEN_JSON_<N> to the base64-encoded contents of
a valid token JSON.  auth.py will write it to the token_path on startup
so the standard flow works identically in CI and locally.
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

    Parameters
    ----------
    db : Database instance for quota tracking.
    """

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db      = db or Database()
        self._clients = get_youtube_clients()
        self._db.init()

        # Hydrate any CI-injected base64 token secrets to disk
        for client in self._clients:
            self._hydrate_ci_token(client)

    # ── Public ─────────────────────────────────────────────────────────────

    def get_service(self, client_index: Optional[int] = None):
        """
        Return an authenticated YouTube API service object.

        If client_index is provided, use that specific client (1-based).
        Otherwise, auto-select the first non-exhausted client.

        Parameters
        ----------
        client_index : Force a specific client (1 | 2 | 3).  None = auto.

        Returns
        -------
        googleapiclient Resource object ready for API calls.

        Raises
        ------
        QuotaExhaustedError : No available client has remaining quota.
        ValueError          : Requested client_index is not configured.
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
        Return the index of the first non-exhausted client without
        building a full service object.  Used by uploader.py to log
        which client was used before the upload starts.
        """
        for client in self._clients:
            if self._db.is_quota_safe(client.index, UPLOAD_COST_UNITS):
                return client.index
        raise QuotaExhaustedError("All YouTube clients exhausted.")

    def invalidate_client(self, client_index: int) -> None:
        """
        Mark a client as exhausted by logging 10 000 units for today.
        Called by uploader.py when it receives an HTTP 403 quotaExceeded.
        Forces rotation to the next client on the next upload attempt.
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
        Load cached credentials or run the OAuth flow.

        1. Try to load from token_path JSON.
        2. If expired but refresh_token present → refresh automatically.
        3. If no valid token → run InstalledAppFlow (opens browser locally;
           in CI the token must be pre-injected via _hydrate_ci_token).
        """
        creds: Optional[Credentials] = None
        token_path = Path(client.token_path)

        # Load existing token
        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(token_path), _SCOPES
                )
                logger.debug(
                    "Auth: loaded cached token for client %d.", client.index
                )
            except Exception as exc:
                logger.warning(
                    "Auth: failed to load token for client %d (%s). "
                    "Will re-authorise.", client.index, exc
                )
                creds = None

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info(
                    "Auth: refreshed token for client %d.", client.index
                )
                self._save_token(creds, token_path)
            except Exception as exc:
                logger.warning(
                    "Auth: token refresh failed for client %d (%s). "
                    "Will re-authorise.", client.index, exc
                )
                creds = None

        # Full OAuth flow (local only — CI must pre-inject tokens)
        if not creds or not creds.valid:
            secret_path = Path(client.client_secret)
            
            # --- TWEAK FOR CI ---
            # If secret_path doesn't exist, try to write it from the raw Env Var (which is what GitHub injects)
            if not secret_path.exists():
                 env_secret = os.getenv(f"YT_CLIENT_SECRET_{client.index}")
                 if env_secret:
                     try:
                         # Attempt to decode if user stored it as Base64 (like the tokens)
                         decoded = base64.b64decode(env_secret).decode("utf-8")
                         secret_path.write_text(decoded, encoding="utf-8")
                     except Exception:
                         # If it's not base64, just write the raw JSON
                         secret_path.write_text(env_secret, encoding="utf-8")
            
            if not secret_path.exists():
                raise FileNotFoundError(
                    f"Client secret not found: {secret_path}\n"
                    f"Download it from Google Cloud Console and set "
                    f"YT_CLIENT_SECRET_{client.index} in your .env."
                )
            logger.info(
                "Auth: starting OAuth flow for client %d (%s). "
                "A browser window will open …",
                client.index, client.label,
            )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(secret_path), _SCOPES
            )
            creds = flow.run_local_server(port=0)
            self._save_token(creds, token_path)
            logger.info(
                "Auth: token saved for client %d → %s",
                client.index, token_path,
            )

        return creds

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _get_client_by_index(self, index: int) -> YouTubeClient:
        for c in self._clients:
            if c.index == index:
                return c
        raise ValueError(
            f"YouTube client index {index} is not configured. "
            f"Configured indices: {[c.index for c in self._clients]}"
        )

    @staticmethod
    def _save_token(creds: Credentials, token_path: Path) -> None:
        """Persist credentials to disk as JSON."""
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        logger.debug("Auth: token written to %s", token_path)

    @staticmethod
    def _hydrate_ci_token(client: YouTubeClient) -> None:
        """
        In GitHub Actions, decode a base64 token secret and write it
        to the expected token_path so the standard flow works unchanged.

        Env var pattern: YT_TOKEN_JSON_1, YT_TOKEN_JSON_2, YT_TOKEN_JSON_3
        Value: base64-encoded contents of a valid token JSON file.
        """
        env_var = f"YT_TOKEN_JSON_{client.index}"
        b64_token = os.getenv(env_var, "").strip()
        if not b64_token:
            return   # Not running in CI or not set — skip silently

        token_path = Path(client.token_path)
        if token_path.exists():
            return   # Already on disk — don't overwrite

        try:
            token_json = base64.b64decode(b64_token).decode("utf-8")
            # Validate it's real JSON before writing
            json.loads(token_json)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(token_json, encoding="utf-8")
            logger.info(
                "Auth: hydrated CI token for client %d → %s",
                client.index, token_path,
            )
        except Exception as exc:
            logger.error(
                "Auth: failed to hydrate CI token for client %d "
                "from env var %s: %s",
                client.index, env_var, exc,
            )
