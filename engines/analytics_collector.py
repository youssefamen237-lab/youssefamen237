"""
engines/analytics_collector.py
Karma Vault Stories — Analytics Collection Engine
Queries YouTube Analytics API v2 + Data API v3 for all recently uploaded
videos in the publication log. Persists per-video metrics to the analytics
store. Runs at pipeline START so heuristics updates happen before story
selection, voice, and SEO decisions — completing the self-learning loop.
"""

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from config.settings import ACTIVE_YT_PACKS, YT_CHANNEL_ID
from config.constants import ANALYTICS_TRACKED_FIELDS
from utils.logger import get_logger
from utils.models import DailyRunContext
from utils.file_manager import (
    load_publication_log, save_json, load_json,
    ANALYTICS_DIR,
)

log = get_logger(__name__)

_ANALYTICS_STORE   = "analytics/analytics_records.json"
_ANALYTICS_SCOPES  = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
_COLLECT_DAYS_BACK = 7    # collect data for videos uploaded up to 7 days ago
_MIN_AGE_HOURS     = 48   # skip videos uploaded less than 48h ago (data not yet stable)


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_analytics_collector(ctx: DailyRunContext) -> DailyRunContext:
    """
    Collects YouTube performance data for all recently uploaded videos.
    Appends results to the analytics store for the heuristics engine to read.
    Non-fatal — if all API calls fail, pipeline continues unaffected.
    """
    log.info("Analytics collector starting...")

    pub_log = load_publication_log()
    if not pub_log:
        log.info("Publication log empty — no prior uploads to collect analytics for.")
        ctx.mark_stage("analytics_collector")
        return ctx

    # Find videos eligible for analytics collection
    eligible = _find_eligible_videos(pub_log)
    if not eligible:
        log.info("No eligible videos for analytics collection (all too recent or already collected).")
        ctx.mark_stage("analytics_collector")
        return ctx

    log.info(f"Collecting analytics for {len(eligible)} videos...")

    # Try to build an authenticated client (use first active pack)
    youtube_client = None
    analytics_client = None
    for pack in ACTIVE_YT_PACKS:
        try:
            youtube_client, analytics_client = _build_analytics_clients(pack)
            log.info(f"Analytics auth via pack #{pack['pack_id']}")
            break
        except Exception as exc:
            log.warning(f"Analytics auth failed for pack #{pack['pack_id']}: {exc}")
            continue

    # Load existing analytics records
    existing = load_json(_ANALYTICS_STORE, default=[])
    existing_ids = {r.get("video_id") for r in existing}
    new_records: list[dict] = []

    for entry in eligible:
        vid_id = entry.get("youtube_video_id")
        if not vid_id or vid_id in existing_ids:
            continue

        record = _collect_single_video(
            vid_id, entry, youtube_client, analytics_client
        )
        if record:
            new_records.append(record)
            existing_ids.add(vid_id)
            log.info(
                f"  {vid_id}: views={record.get('views',0)}, "
                f"ctr={record.get('ctr',0):.3f}, "
                f"avg_dur={record.get('avg_view_duration_sec',0):.0f}s"
            )
            _mark_analytics_collected(pub_log, vid_id)
            time.sleep(0.3)

    if new_records:
        all_records = existing + new_records
        # Keep last 500 records
        all_records = all_records[-500:]
        save_json(_ANALYTICS_STORE, all_records)
        log.info(f"Analytics store updated: {len(new_records)} new records "
                 f"({len(all_records)} total).")

    ctx.mark_stage("analytics_collector")
    return ctx


# ─────────────────────────────────────────────
# ELIGIBILITY FILTER
# ─────────────────────────────────────────────

def _find_eligible_videos(pub_log: list[dict]) -> list[dict]:
    """
    Returns publication log entries that:
    - Have a youtube_video_id
    - Were uploaded at least MIN_AGE_HOURS ago (data is stable)
    - Were uploaded at most COLLECT_DAYS_BACK days ago
    - Have not already had analytics collected
    """
    now = datetime.now(timezone.utc)
    eligible = []
    for entry in pub_log:
        vid_id = entry.get("youtube_video_id")
        if not vid_id:
            continue
        if entry.get("analytics_collected"):
            continue
        logged_at_str = entry.get("logged_at", "")
        if not logged_at_str:
            continue
        try:
            logged_at = datetime.fromisoformat(logged_at_str.replace("Z", "+00:00"))
            age_hours = (now - logged_at).total_seconds() / 3600
            if age_hours < _MIN_AGE_HOURS:
                continue
            if age_hours > _COLLECT_DAYS_BACK * 24:
                continue
            eligible.append(entry)
        except (ValueError, TypeError):
            continue
    return eligible


# ─────────────────────────────────────────────
# API CLIENT BUILDER
# ─────────────────────────────────────────────

def _build_analytics_clients(pack: dict) -> tuple:
    """Builds both YouTube Data API and Analytics API clients."""
    creds = Credentials(
        token=None,
        refresh_token=pack["refresh_token"],
        client_id=pack["client_id"],
        client_secret=pack["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=_ANALYTICS_SCOPES + [
            "https://www.googleapis.com/auth/youtube.readonly",
        ],
    )
    creds.refresh(Request())
    youtube   = build("youtube",          "v3",  credentials=creds, cache_discovery=False)
    analytics = build("youtubeAnalytics", "v2",  credentials=creds, cache_discovery=False)
    return youtube, analytics


# ─────────────────────────────────────────────
# SINGLE VIDEO DATA COLLECTION
# ─────────────────────────────────────────────

def _collect_single_video(
    video_id:         str,
    pub_entry:        dict,
    youtube_client,
    analytics_client,
) -> Optional[dict]:
    """
    Collects all available metrics for one video.
    Tries Analytics API first (full metrics), falls back to Data API (basic stats).
    """
    record = {
        "video_id":             video_id,
        "collected_at":         datetime.now(timezone.utc).isoformat(),
        # Publication context (needed by heuristics engine for attribution)
        "pillar":               pub_entry.get("pillar", ""),
        "country":              pub_entry.get("country", ""),
        "voice_gender":         pub_entry.get("voice_gender", ""),
        "thumbnail_template_id": pub_entry.get("thumbnail_template_id", ""),
        "formula_idx":          pub_entry.get("formula_idx", "0"),
        "yt_pack_used":         pub_entry.get("yt_pack_used", 0),
        # Metrics (filled below)
        "views":                0,
        "impressions":          0,
        "ctr":                  0.0,
        "watch_time_sec":       0.0,
        "avg_view_duration_sec": 0.0,
        "subscribers_gained":   0,
        "likes":                0,
    }

    # ── Try YouTube Analytics API ─────────────────────────────────
    if analytics_client:
        try:
            record = _fetch_analytics_metrics(video_id, record, analytics_client)
            return record
        except HttpError as exc:
            log.warning(f"Analytics API failed for {video_id} ({exc.resp.status}) — "
                        f"falling back to Data API.")
        except Exception as exc:
            log.warning(f"Analytics API error for {video_id}: {exc}")

    # ── Fall back to YouTube Data API (basic stats) ───────────────
    if youtube_client:
        try:
            record = _fetch_data_api_stats(video_id, record, youtube_client)
            return record
        except Exception as exc:
            log.warning(f"Data API fallback also failed for {video_id}: {exc}")

    return None


def _fetch_analytics_metrics(
    video_id:         str,
    record:           dict,
    analytics_client,
) -> dict:
    """
    Queries YouTube Analytics API v2 for full metrics.
    Uses 7-day date range to capture recent performance.
    """
    end_date   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    response = analytics_client.reports().query(
        ids=f"channel=={YT_CHANNEL_ID}" if YT_CHANNEL_ID else "channel==MINE",
        startDate=start_date,
        endDate=end_date,
        metrics=(
            "views,estimatedMinutesWatched,averageViewDuration,"
            "subscribersGained,impressions,impressionClickThroughRate"
        ),
        filters=f"video=={video_id}",
        dimensions="",
    ).execute()

    rows = response.get("rows", [])
    if rows:
        row = rows[0]
        # Column order matches metrics string above
        record["views"]                  = int(row[0])   if len(row) > 0 else 0
        watch_min                        = float(row[1]) if len(row) > 1 else 0.0
        record["watch_time_sec"]         = watch_min * 60
        record["avg_view_duration_sec"]  = float(row[2]) if len(row) > 2 else 0.0
        record["subscribers_gained"]     = int(row[3])   if len(row) > 3 else 0
        record["impressions"]            = int(row[4])   if len(row) > 4 else 0
        record["ctr"]                    = float(row[5]) if len(row) > 5 else 0.0

    return record


def _fetch_data_api_stats(
    video_id:       str,
    record:         dict,
    youtube_client,
) -> dict:
    """
    Falls back to YouTube Data API v3 for basic statistics.
    Available without Analytics scope — just needs youtube.readonly.
    """
    response = youtube_client.videos().list(
        part="statistics",
        id=video_id,
    ).execute()

    items = response.get("items", [])
    if items:
        stats = items[0].get("statistics", {})
        record["views"]  = int(stats.get("viewCount",  0))
        record["likes"]  = int(stats.get("likeCount",  0))
    return record


# ─────────────────────────────────────────────
# PUBLICATION LOG UPDATE
# ─────────────────────────────────────────────

def _mark_analytics_collected(pub_log: list[dict], video_id: str) -> None:
    """
    Updates the in-memory publication log entry and persists it.
    Marks analytics_collected=True so this video is not re-queried.
    """
    from utils.file_manager import save_json, PUBLICATION_LOG_FILE
    for entry in pub_log:
        if entry.get("youtube_video_id") == video_id:
            entry["analytics_collected"] = True
            break
    try:
        save_json(PUBLICATION_LOG_FILE, pub_log)
    except Exception as exc:
        log.warning(f"Could not persist analytics_collected flag: {exc}")
