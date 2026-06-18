"""
storage/r2_client.py

Singleton Cloudflare R2 client — S3-compatible object storage for every
media artefact produced by the YouTube Automation System.

Bucket folder layout
────────────────────
  media/raw/{queue_id}/     Raw footage clips downloaded from provider APIs
  audio/{queue_id}/         Generated voice audio (ElevenLabs / edge-tts)
  subtitles/{queue_id}/     Word-level SRT file
  thumbnails/{queue_id}/    Long-form thumbnail JPEG
  music/                    Background music tracks  (persistent, never deleted)
  finals/{queue_id}/        Final assembled MP4 ready for YouTube upload
  archive/{year}/{month}/   Long-term archive of published finals

Required GitHub Secrets
───────────────────────
  ACCOUNT_ID_CLOUDFLARE_R2   Cloudflare account ID (plain string)

  S3_API_CLOUDFLARE_R2       One of two formats:
      Option A (JSON):  {"access_key_id":"xxx","secret_access_key":"xxx"}
      Option B (plain): just the R2 Access Key ID string

  CLOUDFLARE_TOKEN            R2 Secret Access Key  (used when S3_API is Option B)
  CLOUDFLARE_API              Fallback secret key name (if CLOUDFLARE_TOKEN is unset)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import boto3
import structlog
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# R2 path helpers — single source of truth for every key pattern
# ─────────────────────────────────────────────────────────────────────────────

class R2Paths:
    """
    Static helper that generates canonical R2 object keys.
    Import this class anywhere a key string is needed.
    """

    @staticmethod
    def raw_clip(queue_id: str, filename: str) -> str:
        return f"media/raw/{queue_id}/{filename}"

    @staticmethod
    def raw_prefix(queue_id: str) -> str:
        return f"media/raw/{queue_id}/"

    @staticmethod
    def audio(queue_id: str, filename: str = "voice.mp3") -> str:
        return f"audio/{queue_id}/{filename}"

    @staticmethod
    def audio_prefix(queue_id: str) -> str:
        return f"audio/{queue_id}/"

    @staticmethod
    def subtitle(queue_id: str) -> str:
        return f"subtitles/{queue_id}/subtitles.srt"

    @staticmethod
    def subtitle_prefix(queue_id: str) -> str:
        return f"subtitles/{queue_id}/"

    @staticmethod
    def thumbnail(queue_id: str) -> str:
        return f"thumbnails/{queue_id}/thumb.jpg"

    @staticmethod
    def thumbnail_prefix(queue_id: str) -> str:
        return f"thumbnails/{queue_id}/"

    @staticmethod
    def music_track(filename: str) -> str:
        return f"music/{filename}"

    @staticmethod
    def final_video(queue_id: str) -> str:
        return f"finals/{queue_id}/final.mp4"

    @staticmethod
    def final_prefix(queue_id: str) -> str:
        return f"finals/{queue_id}/"

    @staticmethod
    def archive(queue_id: str, year: int, month: int) -> str:
        return f"archive/{year}/{month:02d}/{queue_id}.mp4"


# ─────────────────────────────────────────────────────────────────────────────
# Transfer configuration for multipart uploads
# ─────────────────────────────────────────────────────────────────────────────

_TRANSFER_CONFIG = TransferConfig(
    multipart_threshold=10 * 1024 * 1024,   # 10 MB
    max_concurrency=4,
    multipart_chunksize=10 * 1024 * 1024,
    use_threads=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# Singleton client
# ─────────────────────────────────────────────────────────────────────────────

class R2Client:
    """
    Thread-safe singleton wrapper around boto3 for Cloudflare R2.
    All upload / download / delete / list operations go through this class.
    """

    _instance: Optional[R2Client] = None
    _s3: Optional[object] = None
    _bucket: str = ""
    _initialized: bool = False

    def __new__(cls) -> R2Client:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._bootstrap()
        self._initialized = True

    # ── Initialisation ────────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        account_id = os.getenv("ACCOUNT_ID_CLOUDFLARE_R2", "").strip()
        if not account_id:
            raise ValueError(
                "ACCOUNT_ID_CLOUDFLARE_R2 is not set in GitHub Secrets."
            )

        access_key_id, secret_access_key = self._resolve_credentials()
        endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
        self._bucket = self._resolve_bucket_name()

        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "adaptive"},
            ),
        )

        # Verify connectivity on startup
        try:
            self._s3.head_bucket(Bucket=self._bucket)
            logger.info("r2_client_ready", bucket=self._bucket, endpoint=endpoint)
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code == "404":
                # Bucket does not yet exist — create it
                self._s3.create_bucket(Bucket=self._bucket)
                logger.info("r2_bucket_created", bucket=self._bucket)
            elif error_code in ("403", "401"):
                raise ValueError(
                    f"R2 credentials rejected by Cloudflare (HTTP {error_code}). "
                    "Check S3_API_CLOUDFLARE_R2 and CLOUDFLARE_TOKEN secrets."
                ) from exc
            else:
                raise

    @staticmethod
    def _resolve_credentials() -> tuple[str, str]:
        """
        Resolve R2 Access Key ID and Secret Access Key from GitHub Secrets.

        Priority:
          1. S3_API_CLOUDFLARE_R2 as JSON {"access_key_id":"...","secret_access_key":"..."}
          2. S3_API_CLOUDFLARE_R2 as plain Access Key ID + CLOUDFLARE_TOKEN as secret
          3. S3_API_CLOUDFLARE_R2 as plain Access Key ID + CLOUDFLARE_API as secret
        """
        s3_api_raw = os.getenv("S3_API_CLOUDFLARE_R2", "").strip()
        cloudflare_token = os.getenv("CLOUDFLARE_TOKEN", "").strip()
        cloudflare_api = os.getenv("CLOUDFLARE_API", "").strip()

        access_key_id = ""
        secret_access_key = ""

        # Attempt JSON parse first
        try:
            creds = json.loads(s3_api_raw)
            access_key_id = (
                creds.get("access_key_id")
                or creds.get("key_id")
                or creds.get("access_key")
                or ""
            )
            secret_access_key = (
                creds.get("secret_access_key")
                or creds.get("secret_key")
                or creds.get("secret")
                or ""
            )
        except (json.JSONDecodeError, TypeError):
            # S3_API_CLOUDFLARE_R2 is a plain string (the Access Key ID)
            access_key_id = s3_api_raw

        # Fill in secret from environment if JSON did not supply it
        if not secret_access_key:
            secret_access_key = cloudflare_token or cloudflare_api

        if not access_key_id:
            raise ValueError(
                "R2 Access Key ID could not be resolved.  "
                "Set S3_API_CLOUDFLARE_R2 to a JSON object or a plain Access Key ID string."
            )
        if not secret_access_key:
            raise ValueError(
                "R2 Secret Access Key could not be resolved.  "
                "Set CLOUDFLARE_TOKEN (or CLOUDFLARE_API) to your R2 Secret Access Key."
            )

        return access_key_id, secret_access_key

    @staticmethod
    def _resolve_bucket_name() -> str:
        """Reads bucket name from Supabase channel_config, falls back to env var."""
        try:
            from storage.supabase_client import get_db
            db = get_db()
            raw = db.get_config("r2_bucket_name")
            if isinstance(raw, str):
                return raw.strip('"').strip()
            if raw:
                return str(raw).strip()
        except Exception:
            pass
        return os.getenv("R2_BUCKET_NAME", "youtube-automation-media")

    # ── Upload operations ─────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=12),
        reraise=True,
    )
    def upload_file(
        self,
        local_path: str,
        r2_key: str,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Upload a local file to R2.
        Uses multipart for files >10 MB automatically.
        Returns the R2 key on success.
        """
        extra: Dict = {}
        if content_type:
            extra["ContentType"] = content_type
        if metadata:
            extra["Metadata"] = {str(k): str(v) for k, v in metadata.items()}

        self._s3.upload_file(
            local_path,
            self._bucket,
            r2_key,
            ExtraArgs=extra if extra else None,
            Config=_TRANSFER_CONFIG,
        )
        size = Path(local_path).stat().st_size
        logger.info("r2_upload_file", key=r2_key, bytes=size)
        return r2_key

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=12),
        reraise=True,
    )
    def upload_bytes(
        self,
        data: bytes,
        r2_key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload raw bytes to R2.  Returns the R2 key."""
        import io
        self._s3.upload_fileobj(
            io.BytesIO(data),
            self._bucket,
            r2_key,
            ExtraArgs={"ContentType": content_type},
        )
        logger.info("r2_upload_bytes", key=r2_key, bytes=len(data))
        return r2_key

    # ── Download operations ───────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=12),
        reraise=True,
    )
    def download_file(self, r2_key: str, local_path: str) -> str:
        """
        Download an R2 object to a local file.
        Creates parent directories automatically.
        Returns local_path on success.
        """
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self._s3.download_file(self._bucket, r2_key, local_path)
        size = Path(local_path).stat().st_size
        logger.info("r2_download_file", key=r2_key, bytes=size, dest=local_path)
        return local_path

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=12),
        reraise=True,
    )
    def download_bytes(self, r2_key: str) -> bytes:
        """Download an R2 object and return it as raw bytes."""
        response = self._s3.get_object(Bucket=self._bucket, Key=r2_key)
        data: bytes = response["Body"].read()
        logger.info("r2_download_bytes", key=r2_key, bytes=len(data))
        return data

    # ── Delete operations ─────────────────────────────────────────────────────

    def delete_file(self, r2_key: str) -> bool:
        """
        Delete a single object from R2.
        Returns True on success, False if the key did not exist or deletion failed.
        """
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=r2_key)
            logger.info("r2_delete_file", key=r2_key)
            return True
        except ClientError as exc:
            logger.warning("r2_delete_failed", key=r2_key, error=str(exc))
            return False

    def delete_prefix(self, prefix: str) -> int:
        """
        Delete all objects whose key begins with prefix (simulates folder delete).
        Uses the S3 batch delete API (up to 1 000 objects per request).
        Returns the count of deleted objects.
        """
        deleted = 0
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            objects = page.get("Contents", [])
            if not objects:
                continue
            batch = {"Objects": [{"Key": obj["Key"]} for obj in objects]}
            self._s3.delete_objects(Bucket=self._bucket, Delete=batch)
            deleted += len(objects)
        logger.info("r2_delete_prefix", prefix=prefix, deleted=deleted)
        return deleted

    # ── Existence & metadata ──────────────────────────────────────────────────

    def file_exists(self, r2_key: str) -> bool:
        """Return True if the object exists in R2."""
        try:
            self._s3.head_object(Bucket=self._bucket, Key=r2_key)
            return True
        except ClientError:
            return False

    def get_file_metadata(self, r2_key: str) -> Optional[Dict]:
        """
        Return a dict with size_bytes, last_modified, content_type for a key.
        Returns None if the object does not exist.
        """
        try:
            head = self._s3.head_object(Bucket=self._bucket, Key=r2_key)
            return {
                "size_bytes": head["ContentLength"],
                "last_modified": head["LastModified"],
                "content_type": head.get("ContentType", ""),
            }
        except ClientError:
            return None

    def get_file_size(self, r2_key: str) -> Optional[int]:
        """Return file size in bytes, or None if the object does not exist."""
        meta = self.get_file_metadata(r2_key)
        return meta["size_bytes"] if meta else None

    # ── Listing ───────────────────────────────────────────────────────────────

    def list_prefix(self, prefix: str) -> List[Dict]:
        """
        List all objects under a prefix.
        Returns a list of dicts: {key, size_bytes, last_modified}.
        """
        results: List[Dict] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                results.append(
                    {
                        "key": obj["Key"],
                        "size_bytes": obj["Size"],
                        "last_modified": obj["LastModified"],  # tz-aware UTC datetime
                    }
                )
        return results

    # ── Presigned URLs ────────────────────────────────────────────────────────

    def get_presigned_url(self, r2_key: str, expiry_seconds: int = 3_600) -> str:
        """Generate a time-limited presigned download URL."""
        url: str = self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": r2_key},
            ExpiresIn=expiry_seconds,
        )
        return url

    # ── Storage usage ─────────────────────────────────────────────────────────

    def get_storage_usage_bytes(self, prefix: str = "") -> int:
        """
        Sum up the byte size of all objects under a prefix (or entire bucket).
        Use sparingly — iterates every object.
        """
        total = 0
        paginator = self._s3.get_paginator("list_objects_v2")
        params: Dict = {"Bucket": self._bucket}
        if prefix:
            params["Prefix"] = prefix
        for page in paginator.paginate(**params):
            for obj in page.get("Contents", []):
                total += obj["Size"]
        return total

    # ── Hashing utility ───────────────────────────────────────────────────────

    @staticmethod
    def compute_file_hash(file_path: str) -> str:
        """
        Compute the SHA-256 hash of a local file.
        Used to detect duplicate visual assets before registering them.
        """
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65_536), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    @staticmethod
    def compute_bytes_hash(data: bytes) -> str:
        """Compute the SHA-256 hash of a bytes object."""
        return hashlib.sha256(data).hexdigest()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def bucket(self) -> str:
        return self._bucket


# ─────────────────────────────────────────────────────────────────────────────
# Module-level accessor
# ─────────────────────────────────────────────────────────────────────────────

_r2_instance: Optional[R2Client] = None


def get_r2() -> R2Client:
    """Return the process-level singleton R2Client."""
    global _r2_instance
    if _r2_instance is None:
        _r2_instance = R2Client()
    return _r2_instance
