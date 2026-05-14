"""
engines/youtube_uploader.py
Karma Vault Stories — YouTube Upload Engine + Quota/Credential Rotation Manager
Rotates across 3 OAuth2 credential packs. On quota exhaustion or auth failure,
falls back to the next pack automatically. If all 3 packs fail, triggers the
Emergency Export Engine to guarantee no generated content is ever lost.
"""

import os
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from config.settings import (
    YOUTUBE_CREDENTIAL_PACKS, ACTIVE_YT_PACKS, YT_CHANNEL_ID,
)
from utils.logger import get_logger
from utils.models import DailyRunContext
from utils.file_manager import append_publication_log

log = get_logger(__name__)

_UPLOAD_CHUNK_SIZE = 50 * 1024 * 1024   # 50 MB — Google's recommended chunk floor
_YT_CATEGORY_ID   = "22"                # People & Blogs
_YT_LANGUAGE      = "en"
_YT_PRIVACY       = "public"
_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]
# Non-retriable error codes — don't burn retries on these
_FATAL_HTTP_CODES = {400, 401, 403}


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_youtube_uploader(ctx: DailyRunContext) -> DailyRunContext:
    """
    Attempts upload across all active credential packs.
    Sets ctx.youtube_video_id and ctx.upload_status on success.
    Triggers emergency_export if all packs fail.
    """
    if not ctx.long_video_path or not Path(ctx.long_video_path).exists():
        log.error("No long video file — cannot upload.")
        ctx.upload_status = "failed_no_video"
        _run_emergency_export(ctx)
        return ctx

    packs = ACTIVE_YT_PACKS
    if not packs:
        log.error("No active YouTube credential packs — cannot upload.")
        ctx.upload_status = "failed_no_credentials"
        _run_emergency_export(ctx)
        return ctx

    if ctx.dry_run:
        log.info("DRY RUN — skipping YouTube upload.")
        ctx.upload_status = "dry_run_skipped"
        return ctx

    # Rotate through packs
    for pack in packs:
        pid = pack["pack_id"]
        log.info(f"Attempting upload with credential pack #{pid}...")
        try:
            video_id, short_id = _upload_with_pack(pack, ctx)
            if video_id:
                ctx.youtube_video_id = video_id
                ctx.youtube_short_id = short_id
                ctx.yt_pack_used     = pid
                ctx.upload_status    = "uploaded"
                _log_publication(ctx)
                log.info(
                    f"Upload SUCCESS via pack #{pid}. "
                    f"video_id={video_id} short_id={short_id}"
                )
                return ctx
        except HttpError as exc:
            code = exc.resp.status
            log.warning(f"Pack #{pid} HttpError {code}: {exc.error_details}")
            if code in _FATAL_HTTP_CODES:
                log.warning(f"Fatal HTTP {code} on pack #{pid} — trying next pack.")
            continue
        except Exception as exc:
            log.warning(f"Pack #{pid} upload error: {exc}")
            continue

    # All packs failed
    log.error("All 3 YouTube credential packs failed. Triggering emergency export.")
    ctx.upload_status = "failed_all_packs"
    _run_emergency_export(ctx)
    return ctx


# ─────────────────────────────────────────────
# PER-PACK UPLOAD FLOW
# ─────────────────────────────────────────────

def _upload_with_pack(
    pack: dict,
    ctx:  DailyRunContext,
) -> tuple[Optional[str], Optional[str]]:
    """
    Full upload flow for one credential pack:
    1. Build authenticated YouTube client
    2. Upload long video
    3. Set thumbnail
    4. Upload short
    Returns (video_id, short_id). Raises on non-retriable errors.
    """
    youtube = _build_client(pack)

    # Upload long video
    long_body = _build_video_body(ctx, is_short=False)
    video_id  = _upload_video_file(youtube, ctx.long_video_path, long_body)
    if not video_id:
        raise RuntimeError("Long video upload returned no ID.")

    # Set thumbnail (non-fatal if fails)
    if ctx.thumbnail_path and Path(ctx.thumbnail_path).exists():
        try:
            _set_thumbnail(youtube, video_id, ctx.thumbnail_path)
            log.info(f"Thumbnail set for {video_id}")
        except Exception as exc:
            log.warning(f"Thumbnail set failed (non-fatal): {exc}")

    # Upload short (non-fatal if fails)
    short_id = None
    if ctx.short_video_path and Path(ctx.short_video_path).exists():
        try:
            short_body = _build_video_body(ctx, is_short=True)
            short_id   = _upload_video_file(youtube, ctx.short_video_path, short_body)
            log.info(f"Short uploaded: {short_id}")
        except Exception as exc:
            log.warning(f"Short upload failed (non-fatal): {exc}")

    return video_id, short_id


# ─────────────────────────────────────────────
# AUTHENTICATION
# ─────────────────────────────────────────────

def _build_client(pack: dict):
    """
    Builds an authenticated YouTube API client using the pack's refresh token.
    Automatically refreshes the access token.
    """
    creds = Credentials(
        token=None,
        refresh_token=pack["refresh_token"],
        client_id=pack["client_id"],
        client_secret=pack["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=_SCOPES,
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


# ─────────────────────────────────────────────
# VIDEO UPLOAD (RESUMABLE)
# ─────────────────────────────────────────────

def _upload_video_file(youtube, file_path: str, body: dict) -> Optional[str]:
    """
    Uploads a video file using the YouTube resumable upload API.
    Handles chunked upload with progress logging.
    Returns the YouTube video ID on success.
    """
    file_path = str(file_path)
    media = MediaFileUpload(
        file_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=_UPLOAD_CHUNK_SIZE,
    )
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    retry_count = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                if pct % 20 == 0:
                    log.info(f"  Upload progress: {pct}%")
        except HttpError as exc:
            if exc.resp.status in (500, 502, 503, 504) and retry_count < 5:
                retry_count += 1
                wait = 2 ** retry_count
                log.warning(f"Server error {exc.resp.status} — retry {retry_count} in {wait}s")
                time.sleep(wait)
            else:
                raise
        except Exception as exc:
            if retry_count < 3:
                retry_count += 1
                time.sleep(4)
                log.warning(f"Upload chunk error (retry {retry_count}): {exc}")
            else:
                raise

    return response.get("id") if response else None


# ─────────────────────────────────────────────
# THUMBNAIL
# ─────────────────────────────────────────────

def _set_thumbnail(youtube, video_id: str, thumbnail_path: str) -> None:
    """Uploads the thumbnail and associates it with the video."""
    with open(thumbnail_path, "rb") as thumb_file:
        media = MediaIoBaseUpload(
            io.BytesIO(thumb_file.read()),
            mimetype="image/jpeg",
            resumable=False,
        )
    youtube.thumbnails().set(
        videoId=video_id,
        media_body=media,
    ).execute()


# ─────────────────────────────────────────────
# METADATA BUILDER
# ─────────────────────────────────────────────

def _build_video_body(ctx: DailyRunContext, is_short: bool = False) -> dict:
    """
    Builds the YouTube video metadata dict from ctx.seo_metadata.
    Shorts append #Shorts to title and description to trigger Shorts shelf.
    """
    seo      = ctx.seo_metadata or {}
    story    = ctx.selected_story
    title    = seo.get("title", story.title if story else "Dark File")[:100]
    desc     = seo.get("description", "")[:4800]
    tags     = seo.get("tags", [])[:15]
    hashtags = seo.get("hashtags", ["#KarmaVaultStories"])

    if is_short:
        title = (title[:88] + " #Shorts") if len(title) <= 88 else title[:91] + "..."
        desc  = f"#Shorts\n\n{desc[:200]}\n\n{'  '.join(hashtags)}"
    else:
        if hashtags:
            desc = desc + "\n\n" + "  ".join(hashtags)

    return {
        "snippet": {
            "title":           title,
            "description":     desc,
            "tags":            tags,
            "categoryId":      _YT_CATEGORY_ID,
            "defaultLanguage": _YT_LANGUAGE,
        },
        "status": {
            "privacyStatus":           _YT_PRIVACY,
            "selfDeclaredMadeForKids": False,
            "madeForKids":             False,
        },
    }


# ─────────────────────────────────────────────
# PUBLICATION LOG
# ─────────────────────────────────────────────

def _log_publication(ctx: DailyRunContext) -> None:
    """
    Appends this run's upload result to the publication log.
    The analytics collector reads this log to know which video IDs to query.
    """
    seo   = ctx.seo_metadata or {}
    story = ctx.selected_story

    entry = {
        "run_id":              ctx.run_id,
        "youtube_video_id":   ctx.youtube_video_id,
        "youtube_short_id":   ctx.youtube_short_id,
        "title":              seo.get("title", ""),
        "pillar":             story.pillar if story else "",
        "country":            story.country if story else "",
        "story_label":        story.story_label if story else "",
        "voice_gender":       ctx.voice_gender,
        "thumbnail_template_id": ctx.thumbnail_template_id,
        "formula_idx":        str(seo.get("formula_idx", "0")),
        "yt_pack_used":       ctx.yt_pack_used,
        "upload_status":      ctx.upload_status,
        "estimated_duration_sec": (ctx.script_blueprint or {}).get("estimated_duration_sec", 0),
        "analytics_collected": False,
    }
    append_publication_log(entry)
    log.info(f"Publication log updated for video_id={ctx.youtube_video_id}")


# ─────────────────────────────────────────────
# EMERGENCY EXPORT TRIGGER
# ─────────────────────────────────────────────

def _run_emergency_export(ctx: DailyRunContext) -> None:
    """Imports and runs the emergency export engine inline."""
    try:
        from engines.emergency_export import run_emergency_export
        run_emergency_export(ctx)
    except Exception as exc:
        log.error(f"Emergency export engine itself failed: {exc}")
        # Last-resort fallback: direct file_manager call
        try:
            from utils.file_manager import emergency_export
            from pathlib import Path
            emergency_export(
                run_id=ctx.run_id,
                long_mp4=Path(ctx.long_video_path) if ctx.long_video_path else None,
                short_mp4=Path(ctx.short_video_path) if ctx.short_video_path else None,
                thumbnail=Path(ctx.thumbnail_path) if ctx.thumbnail_path else None,
                metadata=(ctx.seo_metadata or {}),
            )
        except Exception as exc2:
            log.critical(f"ALL emergency export paths failed: {exc2}")
