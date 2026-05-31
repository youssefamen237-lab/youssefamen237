"""
utils/r2_cache.py
Karma Vault Stories — Cloudflare R2 Asset Cache
S3-compatible cache for generated video clips and images.
Prevents re-generating identical scene prompts across daily runs.
Gracefully degrades if credentials missing — all ops return False/None.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Optional

from utils.logger import get_logger

log = get_logger(__name__)

_R2_BUCKET       = "karma-vault-stories-clips"
_R2_REGION       = "auto"
_CLIP_TTL_DAYS   = 30    # not enforced here but can be set as R2 lifecycle rule


class R2Cache:
    """
    Thread-safe Cloudflare R2 wrapper (one instance per pipeline run is fine).
    Lazy-initialises the boto3 client on first use.
    """

    _instance: Optional["R2Cache"] = None

    def __init__(self) -> None:
        self._client = None
        self._available = False
        self._init_attempted = False

    # ── Singleton access ────────────────────────────────────────────────────
    @classmethod
    def get(cls) -> "R2Cache":
        if cls._instance is None:
            cls._instance = R2Cache()
        return cls._instance

    # ── Lazy init ───────────────────────────────────────────────────────────
    def _ensure_client(self) -> bool:
        if self._init_attempted:
            return self._available
        self._init_attempted = True

        try:
            from config.settings import (
                S3_API_CLOUDFLARE_R2,
                ACCOUNT_ID_CLOUDFLARE_R2,
                CLOUDFLARE_TOKEN,
            )
        except ImportError:
            log.debug("R2: config.settings missing — cache disabled.")
            return False

        if not (S3_API_CLOUDFLARE_R2 and ACCOUNT_ID_CLOUDFLARE_R2 and CLOUDFLARE_TOKEN):
            log.debug("R2: one or more credential secrets missing — cache disabled.")
            return False

        try:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=f"https://{ACCOUNT_ID_CLOUDFLARE_R2}.r2.cloudflarestorage.com",
                aws_access_key_id=S3_API_CLOUDFLARE_R2,
                aws_secret_access_key=CLOUDFLARE_TOKEN,
                config=Config(
                    signature_version="s3v4",
                    connect_timeout=10,
                    read_timeout=60,
                    retries={"max_attempts": 2},
                ),
                region_name=_R2_REGION,
            )
            self._ensure_bucket()
            self._available = True
            log.info("R2 cache: connected successfully.")
        except ImportError:
            log.warning("R2 cache: boto3 not installed (pip install boto3).")
        except Exception as exc:
            log.warning(f"R2 cache: init failed — {exc}. Cache disabled for this run.")

        return self._available

    def is_available(self) -> bool:
        return self._ensure_client()

    # ── Core operations ─────────────────────────────────────────────────────
    def get_clip(self, cache_key: str, dest_path: Path) -> bool:
        """
        Downloads a cached clip from R2 to dest_path.
        Returns True if the object exists and was downloaded successfully.
        """
        if not self._ensure_client():
            return False
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            self._client.download_file(_R2_BUCKET, cache_key, str(dest_path))
            if dest_path.exists() and dest_path.stat().st_size > 20_000:
                log.debug(f"R2 cache HIT: {cache_key[:32]}...")
                return True
            dest_path.unlink(missing_ok=True)
            return False
        except self._client.exceptions.NoSuchKey:
            return False
        except Exception as exc:
            log.debug(f"R2 get_clip failed ({cache_key[:20]}): {exc}")
            return False

    def put_clip(self, cache_key: str, src_path: Path) -> bool:
        """
        Uploads a generated clip to R2.
        Non-fatal — a failed upload just means the next run will re-generate.
        """
        if not self._ensure_client():
            return False
        if not src_path.exists() or src_path.stat().st_size < 20_000:
            return False
        try:
            self._client.upload_file(
                str(src_path),
                _R2_BUCKET,
                cache_key,
                ExtraArgs={"ContentType": "video/mp4"},
            )
            log.debug(
                f"R2 cache WRITE: {cache_key[:32]}... "
                f"({src_path.stat().st_size // 1024}KB)"
            )
            return True
        except Exception as exc:
            log.warning(f"R2 put_clip failed ({cache_key[:20]}): {exc}")
            return False

    def get_image(self, cache_key: str, dest_path: Path) -> bool:
        """Downloads a cached still image (JPEG/PNG) from R2."""
        if not self._ensure_client():
            return False
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            self._client.download_file(_R2_BUCKET, cache_key, str(dest_path))
            return dest_path.exists() and dest_path.stat().st_size > 5_000
        except Exception:
            return False

    def put_image(self, cache_key: str, src_path: Path) -> bool:
        """Uploads a generated still image to R2."""
        if not self._ensure_client():
            return False
        if not src_path.exists():
            return False
        try:
            mime = "image/jpeg" if str(src_path).lower().endswith((".jpg", ".jpeg")) else "image/png"
            self._client.upload_file(
                str(src_path), _R2_BUCKET, cache_key,
                ExtraArgs={"ContentType": mime},
            )
            return True
        except Exception as exc:
            log.debug(f"R2 put_image failed: {exc}")
            return False

    # ── Utilities ───────────────────────────────────────────────────────────
    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=_R2_BUCKET)
        except Exception:
            try:
                self._client.create_bucket(Bucket=_R2_BUCKET)
                log.info(f"R2: created bucket '{_R2_BUCKET}'.")
            except Exception as exc:
                log.warning(f"R2: could not create bucket '{_R2_BUCKET}': {exc}")
                self._available = False


# ── Module-level cache key helpers ──────────────────────────────────────────

def clip_cache_key(prompt: str, duration_sec: int = 5) -> str:
    """
    Deterministic cache key for a video clip.
    Two scene prompts that hash identically share one R2 object.
    """
    digest = hashlib.sha256(f"{prompt}|{duration_sec}".encode()).hexdigest()[:40]
    return f"clips/{digest}.mp4"


def image_cache_key(prompt: str) -> str:
    """Deterministic cache key for a generated still image."""
    digest = hashlib.sha256(prompt.encode()).hexdigest()[:40]
    return f"images/{digest}.jpg"
  
