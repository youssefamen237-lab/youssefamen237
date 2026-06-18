"""
youtube/management/management_client.py

Read-only YouTube access using the isolated management credential set (Key 4).
Used exclusively for analytics retrieval — never for uploads
(see youtube/upload/upload_client.py for the upload-rotation client).

Required GitHub Secrets: YT_CLIENT_ID_4, YT_CLIENT_SECRET_4, YT_REFRESH_TOKEN_4
"""
from __future__ import annotations
from typing import Dict, List, Optional
import requests, structlog
from youtube.upload.key_rotator import get_key_rotator, OAuthCredentials

logger = structlog.get_logger(__name__)

_DATA_API_BASE      = "https://www.googleapis.com/youtube/v3"
_ANALYTICS_API_BASE = "https://youtubeanalytics.googleapis.com/v2"

# ── Metric tiers, most-complete first ───────────────────────────────────────
# Core metrics use extremely well-established names and require only the
# yt-analytics.readonly scope — these should succeed for any channel.
_CORE_METRICS = [
    "views", "estimatedMinutesWatched", "averageViewDuration",
    "averageViewPercentage", "likes", "comments", "shares", "subscribersGained",
]
# Impression/CTR metrics also use yt-analytics.readonly but are occasionally
# unavailable for very new channels with no impression data yet.
_IMPRESSION_METRICS = ["impressions", "impressionClickThroughRate", "cardClicks"]
# Monetary metrics require yt-analytics-monetary.readonly AND an active YPP
# membership — will 400/403 for pre-monetization channels.
_MONETARY_METRICS = ["estimatedRevenue", "cpm", "playbackBasedCpm"]

_METRIC_TIERS: List[List[str]] = [
    _CORE_METRICS + _IMPRESSION_METRICS + _MONETARY_METRICS,   # Tier A — everything
    _CORE_METRICS + _IMPRESSION_METRICS,                       # Tier B — no monetary
    _CORE_METRICS,                                             # Tier C — guaranteed-stable core only
]

_METRIC_COLUMN_MAP: Dict[str, str] = {
    "views":                       "views",
    "estimatedMinutesWatched":     "watch_time_minutes",
    "averageViewDuration":         "avg_view_duration_seconds",
    "averageViewPercentage":       "retention_percentage",
    "likes":                       "likes",
    "comments":                    "comments",
    "shares":                      "shares",
    "subscribersGained":           "subscribers_gained",
    "impressions":                 "impressions",
    "impressionClickThroughRate":  "ctr",
    "cardClicks":                  "card_clicks",
    "estimatedRevenue":            "estimated_revenue_usd",
    "cpm":                         "cpm",
    "playbackBasedCpm":            "rpm",
}

_INT_COLUMNS = frozenset({
    "views", "unique_views", "likes", "comments", "shares",
    "subscribers_gained", "impressions", "card_clicks",
    "end_screen_clicks", "avg_view_duration_seconds",
})


class ManagementClient:

    def __init__(self) -> None:
        self._rotator = get_key_rotator()
        self._creds: Optional[OAuthCredentials] = None

    # ═════════════════════════════════════════════════════════════════════════
    # Public API
    # ═════════════════════════════════════════════════════════════════════════

    def query_video_analytics(
        self, youtube_video_id: str, start_date: str, end_date: str
    ) -> Dict:
        """
        Return a dict matching performance_metrics columns for the given
        video and date range (typically a single day).

        Returns {} if the API succeeded but has no data yet for this video
        (common for very recently published videos).

        Raises RuntimeError only if every metric tier failed with an HTTP error
        (auth failure, quota exhaustion, etc.) — analytics_puller treats this
        as a per-video error and continues with the next video.
        """
        creds = self._get_creds()
        token = self._rotator.get_access_token(creds)

        for metrics in _METRIC_TIERS:
            row = self._query_with_retry(creds, token, youtube_video_id, start_date, end_date, metrics)
            if row is None:
                continue   # this tier's metric names were rejected — try next tier
            if not row:
                return {}  # API call succeeded, video simply has no data for this period
            return self._row_to_metrics(metrics, row)

        raise RuntimeError(
            f"YouTube Analytics query failed for video {youtube_video_id} "
            f"across all {len(_METRIC_TIERS)} metric tiers."
        )

    def get_lifetime_stats(self, youtube_video_ids: List[str]) -> Dict[str, Dict]:
        """
        Return lifetime {viewCount, likeCount, commentCount} per video ID
        via the Data API v3 (supplementary to the period-based Analytics API).
        """
        if not youtube_video_ids:
            return {}

        creds = self._get_creds()
        token = self._rotator.get_access_token(creds)

        try:
            resp = requests.get(
                f"{_DATA_API_BASE}/videos",
                headers={"Authorization": f"Bearer {token}"},
                params={"part": "statistics", "id": ",".join(youtube_video_ids[:50])},
                timeout=20,
            )
            if resp.status_code == 401:
                token = self._rotator.get_access_token(creds, force_refresh=True)
                resp = requests.get(
                    f"{_DATA_API_BASE}/videos",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"part": "statistics", "id": ",".join(youtube_video_ids[:50])},
                    timeout=20,
                )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("lifetime_stats_request_failed", error=str(exc)[:120])
            return {}

        out: Dict[str, Dict] = {}
        for item in resp.json().get("items", []):
            stats = item.get("statistics", {})
            out[item["id"]] = {
                "view_count":    int(stats.get("viewCount", 0)),
                "like_count":    int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
            }
        return out

    def get_channel_statistics(self) -> Dict:
        """
        Return {subscriber_count, view_count, video_count} for the
        authenticated channel via Data API v3 channels.list?mine=true.
        """
        creds = self._get_creds()
        token = self._rotator.get_access_token(creds)

        try:
            resp = requests.get(
                f"{_DATA_API_BASE}/channels",
                headers={"Authorization": f"Bearer {token}"},
                params={"part": "statistics", "mine": "true"},
                timeout=20,
            )
            if resp.status_code == 401:
                token = self._rotator.get_access_token(creds, force_refresh=True)
                resp = requests.get(
                    f"{_DATA_API_BASE}/channels",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"part": "statistics", "mine": "true"},
                    timeout=20,
                )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("channel_statistics_request_failed", error=str(exc)[:120])
            return {}

        items = resp.json().get("items", [])
        if not items:
            return {}
        stats = items[0].get("statistics", {})
        return {
            "subscriber_count": int(stats.get("subscriberCount", 0)),
            "view_count":       int(stats.get("viewCount", 0)),
            "video_count":      int(stats.get("videoCount", 0)),
        }

    def query_channel_analytics(self, start_date: str, end_date: str, metrics: List[str]) -> Dict[str, float]:
        """
        Channel-wide aggregate over [start_date, end_date] — no per-video
        filter, no dimensions.  Returns {raw_metric_name: value}; caller
        interprets the values (raw YouTube Analytics metric names, not the
        performance_metrics column names used by query_video_analytics).
        """
        creds = self._get_creds()
        token = self._rotator.get_access_token(creds)

        row = self._query_channel_with_retry(creds, token, start_date, end_date, metrics)
        if not row:
            return {}
        return {name: float(val) for name, val in zip(metrics, row)}

    # ═════════════════════════════════════════════════════════════════════════
    # Internal
    # ═════════════════════════════════════════════════════════════════════════

    def _get_creds(self) -> OAuthCredentials:
        if self._creds is None:
            self._creds = self._rotator.get_management_credentials()
        return self._creds

    def _query_channel_with_retry(
        self, creds: OAuthCredentials, token: str, start: str, end: str, metrics: List[str]
    ) -> Optional[List]:
        result = self._query_channel_reports(token, start, end, metrics)
        if result is None:
            fresh_token = self._rotator.get_access_token(creds, force_refresh=True)
            result = self._query_channel_reports(fresh_token, start, end, metrics)
        return result

    @staticmethod
    def _query_channel_reports(token: str, start: str, end: str, metrics: List[str]) -> Optional[List]:
        try:
            resp = requests.get(
                f"{_ANALYTICS_API_BASE}/reports",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "ids":       "channel==MINE",
                    "startDate": start,
                    "endDate":   end,
                    "metrics":   ",".join(metrics),
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            logger.debug("channel_analytics_request_error", error=str(exc)[:100])
            return None

        if resp.status_code >= 400:
            logger.debug(
                "channel_analytics_query_rejected",
                status=resp.status_code, metrics=metrics, body=resp.text[:200],
            )
            return None

        rows = resp.json().get("rows", [])
        return rows[0] if rows else []

    def _query_with_retry(

        self, creds: OAuthCredentials, token: str,
        video_id: str, start: str, end: str, metrics: List[str],
    ) -> Optional[List]:
        """
        Query one metric tier.  On a possible-expired-token failure, force a
        token refresh and retry once.  Returns:
          None       -> this tier's request failed (HTTP error)
          []         -> request succeeded, no data rows for this period
          [v1, v2..] -> first data row, aligned with `metrics` order
        """
        result = self._query_reports(token, video_id, start, end, metrics)
        if result is None:
            fresh_token = self._rotator.get_access_token(creds, force_refresh=True)
            result = self._query_reports(fresh_token, video_id, start, end, metrics)
        return result

    @staticmethod
    def _query_reports(
        token: str, video_id: str, start: str, end: str, metrics: List[str]
    ) -> Optional[List]:
        try:
            resp = requests.get(
                f"{_ANALYTICS_API_BASE}/reports",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "ids":        "channel==MINE",
                    "startDate":  start,
                    "endDate":    end,
                    "metrics":    ",".join(metrics),
                    "dimensions": "video",
                    "filters":    f"video=={video_id}",
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            logger.debug("analytics_request_error", video_id=video_id, error=str(exc)[:100])
            return None

        if resp.status_code >= 400:
            logger.debug(
                "analytics_query_rejected",
                video_id=video_id, status=resp.status_code,
                metrics=metrics, body=resp.text[:200],
            )
            return None

        rows = resp.json().get("rows", [])
        return rows[0] if rows else []

    @staticmethod
    def _row_to_metrics(metric_names: List[str], row: List) -> Dict:
        out: Dict = {}
        for name, val in zip(metric_names, row):
            col = _METRIC_COLUMN_MAP.get(name)
            if not col:
                continue
            try:
                out[col] = float(val)
            except (TypeError, ValueError):
                out[col] = 0.0

        # CTR arrives as a fraction (0.0-1.0) — convert to percentage
        if "ctr" in out:
            out["ctr"] = round(out["ctr"] * 100, 4)

        # Approximation / defaults for columns not covered by any metric tier
        out["unique_views"] = out.get("views", 0.0)
        out.setdefault("end_screen_clicks", 0.0)
        out.setdefault("estimated_revenue_usd", 0.0)
        out.setdefault("rpm", 0.0)
        out.setdefault("cpm", 0.0)
        out.setdefault("impressions", 0.0)
        out.setdefault("ctr", 0.0)
        out.setdefault("card_clicks", 0.0)

        for col in _INT_COLUMNS:
            if col in out:
                out[col] = int(round(out[col]))

        return out


_instance: Optional[ManagementClient] = None

def get_management_client() -> ManagementClient:
    global _instance
    if _instance is None:
        _instance = ManagementClient()
    return _instance
