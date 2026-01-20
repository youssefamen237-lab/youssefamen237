from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional

from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


def _chunks(seq: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


class YouTubeMetricsFetcher:
    def __init__(self, *, youtube_service, analytics_service=None) -> None:
        self.youtube = youtube_service
        self.analytics = analytics_service

    def fetch_basic_stats(self, video_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        if not video_ids:
            return out

        for chunk in _chunks(video_ids, 50):
            req = self.youtube.videos().list(part="statistics,snippet,contentDetails", id=",".join(chunk))
            resp = req.execute()
            for item in resp.get("items", []) or []:
                vid = item.get("id")
                if not vid:
                    continue
                stats = item.get("statistics", {}) or {}
                snippet = item.get("snippet", {}) or {}
                content = item.get("contentDetails", {}) or {}
                out[vid] = {
                    "views": int(stats.get("viewCount", 0) or 0),
                    "likes": int(stats.get("likeCount", 0) or 0),
                    "comments": int(stats.get("commentCount", 0) or 0),
                    "favorites": int(stats.get("favoriteCount", 0) or 0),
                    "publishedAt": snippet.get("publishedAt"),
                    "title": snippet.get("title"),
                    "duration": content.get("duration"),
                }
        return out

    def fetch_analytics_last_days(self, *, days_back: int = 30, max_results: int = 200) -> Dict[str, Dict[str, Any]]:
        """Best-effort YouTube Analytics metrics by video for the last N days.

        Requires the refresh token to have yt-analytics.readonly scope.
        """
        if not self.analytics:
            return {}

        end = date.today()
        start = end - timedelta(days=max(1, days_back))

        try:
            req = self.analytics.reports().query(
                ids="channel==MINE",
                startDate=start.isoformat(),
                endDate=end.isoformat(),
                metrics="views,averageViewDuration,averageViewPercentage,likes,comments,shares,subscribersGained",
                dimensions="video",
                maxResults=max_results,
            )
            resp = req.execute()
        except HttpError as e:
            logger.warning("YouTube Analytics API unavailable: %s", getattr(e.resp, "status", None))
            return {}
        except Exception as e:
            logger.warning("YouTube Analytics API error: %s", e)
            return {}

        headers = [h.get("name") for h in (resp.get("columnHeaders") or [])]
        rows = resp.get("rows") or []
        if not headers or not rows:
            return {}

        out: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            try:
                item = dict(zip(headers, row))
                vid = item.get("video")
                if not vid:
                    continue
                out[str(vid)] = {
                    "ya_views": int(item.get("views", 0) or 0),
                    "ya_avg_view_duration": float(item.get("averageViewDuration", 0.0) or 0.0),
                    "ya_avg_view_percentage": float(item.get("averageViewPercentage", 0.0) or 0.0),
                    "ya_likes": int(item.get("likes", 0) or 0),
                    "ya_comments": int(item.get("comments", 0) or 0),
                    "ya_shares": int(item.get("shares", 0) or 0),
                    "ya_subscribers_gained": int(item.get("subscribersGained", 0) or 0),
                }
            except Exception:
                continue

        return out
