"""
manager/analytics_fetcher.py – Quizzaro Analytics Fetcher
===========================================================
Encapsulates all YouTube Data API v3 and YouTube Analytics API v2 calls.
Used exclusively by project_manager.py.

Provides:
  - Channel-level stats (subscribers, total views, video count)
  - Paginated list of recently published Shorts
  - Batch video details (duration, tags, statistics)
  - Per-video analytics (views, watch time, avg view %, CTR, subs gained)
  - Geographic breakdown (top countries by views and watch time)
  - Total channel watch hours for monetisation tracking

Token refresh is handled internally — no token files are ever written to disk.
All methods use tenacity retry with exponential back-off for robustness.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

LOOKBACK_DAYS = 28


class AnalyticsFetcher:

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        channel_id: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._channel_id = channel_id
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

    # ── Token management ───────────────────────────────────────────────────

    def _refresh(self) -> str:
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=15,
        )
        resp.raise_for_status()
        d = resp.json()
        self._access_token = d["access_token"]
        self._token_expiry = datetime.utcnow() + timedelta(seconds=d.get("expires_in", 3500))
        return self._access_token

    def _token(self) -> str:
        if not self._access_token or (self._token_expiry and datetime.utcnow() >= self._token_expiry):
            return self._refresh()
        return self._access_token

    def _creds(self) -> Credentials:
        return Credentials(
            token=self._token(),
            refresh_token=self._refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._client_id,
            client_secret=self._client_secret,
        )

    def _data(self):
        return build("youtube", "v3", credentials=self._creds(), cache_discovery=False)

    def _analytics(self):
        return build("youtubeAnalytics", "v2", credentials=self._creds(), cache_discovery=False)

    # ── Channel stats ──────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
    def get_channel_stats(self) -> dict:
        try:
            resp = self._data().channels().list(
                part="statistics", id=self._channel_id
            ).execute()
            items = resp.get("items", [])
            if not items:
                return {}
            s = items[0]["statistics"]
            return {
                "subscribers": int(s.get("subscriberCount", 0)),
                "total_views": int(s.get("viewCount", 0)),
                "video_count": int(s.get("videoCount", 0)),
            }
        except Exception as exc:
            logger.error(f"[Analytics] channel_stats failed: {exc}")
            return {}

    # ── Recent Shorts list ─────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
    def get_recent_videos(self, max_results: int = 50) -> list[dict]:
        cutoff = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            resp = self._data().search().list(
                part="id,snippet",
                channelId=self._channel_id,
                type="video",
                order="date",
                maxResults=max_results,
                publishedAfter=cutoff,
            ).execute()
            return [
                {
                    "video_id": item["id"]["videoId"],
                    "title": item["snippet"]["title"],
                    "published_at": item["snippet"]["publishedAt"],
                }
                for item in resp.get("items", [])
                if item["id"].get("videoId")
            ]
        except Exception as exc:
            logger.error(f"[Analytics] get_recent_videos failed: {exc}")
            return []

    # ── Batch video details ────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
    def get_video_details(self, video_ids: list[str]) -> dict[str, dict]:
        if not video_ids:
            return {}
        result: dict[str, dict] = {}
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i + 50]
            try:
                resp = self._data().videos().list(
                    part="contentDetails,statistics,snippet",
                    id=",".join(batch),
                ).execute()
                for item in resp.get("items", []):
                    vid_id = item["id"]
                    stats = item.get("statistics", {})
                    snippet = item.get("snippet", {})
                    dur_iso = item.get("contentDetails", {}).get("duration", "PT0S")
                    result[vid_id] = {
                        "views": int(stats.get("viewCount", 0)),
                        "likes": int(stats.get("likeCount", 0)),
                        "comments": int(stats.get("commentCount", 0)),
                        "duration_sec": _parse_iso_duration(dur_iso),
                        "tags": snippet.get("tags", []),
                        "title": snippet.get("title", ""),
                    }
            except Exception as exc:
                logger.warning(f"[Analytics] video_details batch failed: {exc}")
        return result

    # ── Per-video analytics ────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
    def get_video_metrics(self, video_id: str) -> dict:
        end = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        try:
            resp = self._analytics().reports().query(
                ids=f"channel=={self._channel_id}",
                startDate=start,
                endDate=end,
                metrics=(
                    "views,estimatedMinutesWatched,averageViewDuration,"
                    "averageViewPercentage,likes,comments,subscribersGained"
                ),
                dimensions="video",
                filters=f"video=={video_id}",
            ).execute()
            rows = resp.get("rows", [])
            if rows:
                r = rows[0]
                return {
                    "video_id": video_id,
                    "views": int(r[1]),
                    "watch_minutes": float(r[2]),
                    "avg_view_duration_sec": float(r[3]),
                    "avg_view_percent": float(r[4]),
                    "likes": int(r[5]),
                    "comments": int(r[6]),
                    "subs_gained": int(r[7]),
                }
        except Exception as exc:
            logger.warning(f"[Analytics] video_metrics({video_id}) failed: {exc}")
        return {
            "video_id": video_id, "views": 0, "watch_minutes": 0.0,
            "avg_view_duration_sec": 0.0, "avg_view_percent": 0.0,
            "likes": 0, "comments": 0, "subs_gained": 0,
        }

    # ── Geographic analytics ───────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
    def get_geo_breakdown(self, top_n: int = 15) -> list[dict]:
        end = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        try:
            resp = self._analytics().reports().query(
                ids=f"channel=={self._channel_id}",
                startDate=start,
                endDate=end,
                metrics="views,estimatedMinutesWatched,subscribersGained",
                dimensions="country",
                sort="-views",
                maxResults=top_n,
            ).execute()
            return [
                {
                    "country": r[0],
                    "views": int(r[1]),
                    "watch_minutes": float(r[2]),
                    "subs_gained": int(r[3]),
                }
                for r in resp.get("rows", [])
            ]
        except Exception as exc:
            logger.warning(f"[Analytics] geo_breakdown failed: {exc}")
            return []

    # ── Total watch hours (monetisation) ──────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
    def get_total_watch_hours(self) -> float:
        end = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")
        try:
            resp = self._analytics().reports().query(
                ids=f"channel=={self._channel_id}",
                startDate=start,
                endDate=end,
                metrics="estimatedMinutesWatched",
            ).execute()
            rows = resp.get("rows", [])
            if rows:
                return float(rows[0][0]) / 60.0
        except Exception as exc:
            logger.warning(f"[Analytics] watch_hours failed: {exc}")
        return 0.0


# ── ISO 8601 duration parser ───────────────────────────────────────────────

def _parse_iso_duration(iso: str) -> float:
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", iso)
    if not m:
        return 0.0
    h = float(m.group(1) or 0)
    mins = float(m.group(2) or 0)
    s = float(m.group(3) or 0)
    return h * 3600 + mins * 60 + s
