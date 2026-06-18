"""
youtube/upload/key_rotator.py

Required GitHub Secrets (Upload keys 1-3 + Management key 4):
  YT_CLIENT_ID_1/2/3/4, YT_CLIENT_SECRET_1/2/3/4, YT_REFRESH_TOKEN_1/2/3/4
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Optional, Tuple
import requests, structlog
from storage.redis_client import get_redis
from youtube.upload.quota_manager import get_quota_manager

logger = structlog.get_logger(__name__)

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_TOKEN_CACHE_TTL = 3_300  # 55 minutes (Google access tokens last ~60 min)


@dataclass
class OAuthCredentials:
    client_id:     str
    client_secret: str
    refresh_token: str
    key_index:     int   # 1-3 = upload rotation, 4 = management (analytics/playlists/comments)


class KeyRotator:

    def __init__(self) -> None:
        self._redis = get_redis()
        self._quota = get_quota_manager()

    # ── Credential resolution ────────────────────────────────────────────────

    def get_credentials(self, key_index: int) -> OAuthCredentials:
        if key_index not in (1, 2, 3, 4):
            raise ValueError(f"Invalid YouTube key_index: {key_index}")
        cid     = os.environ[f"YT_CLIENT_ID_{key_index}"]
        secret  = os.environ[f"YT_CLIENT_SECRET_{key_index}"]
        refresh = os.environ[f"YT_REFRESH_TOKEN_{key_index}"]
        return OAuthCredentials(cid, secret, refresh, key_index)

    def get_management_credentials(self) -> OAuthCredentials:
        """Key 4 — isolated from upload rotation. Used for analytics, playlists, comments."""
        return self.get_credentials(4)

    # ── Access token (Redis-cached) ──────────────────────────────────────────

    def get_access_token(self, creds: OAuthCredentials, force_refresh: bool = False) -> str:
        cache_key = f"yta:oauth:access_token:{creds.key_index}"

        if not force_refresh:
            try:
                cached = self._redis.get_json(cache_key)
                if cached and cached.get("token"):
                    return cached["token"]
            except Exception:
                pass

        resp = requests.post(
            _TOKEN_URL,
            data={
                "client_id":     creds.client_id,
                "client_secret": creds.client_secret,
                "refresh_token": creds.refresh_token,
                "grant_type":    "refresh_token",
            },
            timeout=20,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"OAuth token refresh failed for key {creds.key_index} "
                f"(HTTP {resp.status_code}): {resp.text[:300]}"
            )

        token = resp.json()["access_token"]
        try:
            self._redis.set_with_ttl(cache_key, {"token": token}, _TOKEN_CACHE_TTL)
        except Exception:
            pass

        logger.debug("oauth_token_refreshed", key_index=creds.key_index)
        return token

    # ── Upload key selection ──────────────────────────────────────────────────

    def select_upload_credentials(self) -> Tuple[int, OAuthCredentials, str]:
        """
        Return (key_index, credentials, access_token) for the upload key with
        the most remaining daily quota.
        Raises RuntimeError if all 3 upload keys are exhausted for today.
        """
        key_index = self._quota.get_best_key()
        if key_index is None:
            raise RuntimeError("All 3 YouTube upload keys have exhausted today's quota.")

        creds = self.get_credentials(key_index)
        token = self.get_access_token(creds)
        return key_index, creds, token

    def get_management_token(self) -> str:
        """Convenience accessor for the isolated management key's access token."""
        creds = self.get_management_credentials()
        return self.get_access_token(creds)


_instance: Optional[KeyRotator] = None

def get_key_rotator() -> KeyRotator:
    global _instance
    if _instance is None:
        _instance = KeyRotator()
    return _instance
