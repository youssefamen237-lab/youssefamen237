"""
analytics/competitor_tracker.py

Discovers and tracks competitor channels per category using the PUBLIC
YouTube Data API v3 (YOUTUBE_API_KEY) — no OAuth, completely independent
of the upload/management credential rotation.

- Discovery: when a category has fewer than _MIN_COMPETITORS_PER_CATEGORY
  active competitors, runs ONE search.list query for that category and
  registers the top channel results.
- Refresh: for every active competitor, refreshes subscriber count,
  lifetime average views, estimated posting frequency, and top-5 videos
  by view count (used as `top_hooks` — real titles that are winning).

Run via: python -m analytics.competitor_tracker
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import requests, structlog

from storage.supabase_client import get_db

logger = structlog.get_logger(__name__)

_API_BASE = "https://www.googleapis.com/youtube/v3"
_MIN_COMPETITORS_PER_CATEGORY    = 3
_DISCOVERY_RESULTS_PER_CATEGORY  = 5
_TOP_VIDEOS_PER_COMPETITOR       = 5

_CATEGORY_QUERIES: Dict[str, str] = {
    "ocean":   "ocean facts shorts",
    "animals": "animal facts shorts",
    "space":   "space facts shorts",
    "nature":  "nature facts shorts",
    "birds":   "bird facts shorts",
    "insects": "insect facts shorts",
}


class CompetitorTracker:

    def __init__(self) -> None:
        self._db = get_db()
        self._api_key = os.getenv("YOUTUBE_API_KEY", "").strip()

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self) -> Dict:
        summary = {"discovered": 0, "refreshed": 0, "errors": 0}

        if not self._api_key:
            logger.warning("competitor_tracker_no_api_key")
            return summary

        for category, query in _CATEGORY_QUERIES.items():
            existing = [c for c in self._active_competitors() if c.get("category") == category]
            if len(existing) >= _MIN_COMPETITORS_PER_CATEGORY:
                continue
            try:
                summary["discovered"] += self._discover(category, query)
            except Exception as exc:
                logger.warning("competitor_discovery_failed", category=category, error=str(exc)[:120])
                summary["errors"] += 1

        for competitor in self._active_competitors():
            try:
                if self._refresh(competitor):
                    summary["refreshed"] += 1
            except Exception as exc:
                logger.warning(
                    "competitor_refresh_failed",
                    channel=competitor.get("channel_name"), error=str(exc)[:120],
                )
                summary["errors"] += 1

        logger.info("competitor_tracker_complete", **summary)
        return summary

    # ── Discovery ─────────────────────────────────────────────────────────────

    def _discover(self, category: str, query: str) -> int:
        params = {
            "part": "snippet", "type": "channel", "q": query,
            "order": "relevance", "maxResults": _DISCOVERY_RESULTS_PER_CATEGORY,
            "key": self._api_key,
        }
        resp = requests.get(f"{_API_BASE}/search", params=params, timeout=20)
        resp.raise_for_status()

        registered = 0
        for item in resp.json().get("items", []):
            snippet = item.get("snippet", {})
            channel_id = snippet.get("channelId") or item.get("id", {}).get("channelId")
            title = snippet.get("channelTitle") or snippet.get("title")
            if not channel_id or not title:
                continue
            try:
                self._db.upsert_competitor({
                    "channel_name":       title[:255],
                    "channel_url":        f"https://www.youtube.com/channel/{channel_id}",
                    "youtube_channel_id": channel_id,
                    "category":           category,
                    "is_active":          True,
                })
                registered += 1
            except Exception as exc:
                logger.debug("competitor_register_skip", channel=title, error=str(exc)[:100])

        logger.info("competitor_discovery_done", category=category, registered=registered)
        return registered

    # ── Refresh ──────────────────────────────────────────────────────────────

    def _refresh(self, competitor: Dict) -> bool:
        channel_id = competitor.get("youtube_channel_id")
        if not channel_id:
            return False

        stats = self._channel_stats(channel_id)
        if not stats:
            return False

        top_videos, top_hooks = self._top_videos(channel_id)

        update: Dict = {
            "channel_name":        competitor["channel_name"],
            "youtube_channel_id":  channel_id,
            "channel_url":         competitor.get("channel_url") or f"https://www.youtube.com/channel/{channel_id}",
            "category":            competitor.get("category"),
            "subscriber_count":    stats["subscriber_count"],
            "avg_views_per_video": stats["avg_views_per_video"],
            "posting_frequency":   stats["posting_frequency"],
            "is_active":           True,
            "last_analyzed_at":    datetime.now(timezone.utc).isoformat(),
        }
        if top_videos:
            update["top_videos"] = top_videos
        if top_hooks:
            update["top_hooks"] = top_hooks

        self._db.upsert_competitor(update)
        return True

    def _channel_stats(self, channel_id: str) -> Optional[Dict]:
        params = {"part": "snippet,statistics", "id": channel_id, "key": self._api_key}
        resp = requests.get(f"{_API_BASE}/channels", params=params, timeout=20)
        resp.raise_for_status()

        items = resp.json().get("items", [])
        if not items:
            return None

        item = items[0]
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})

        subscriber_count = int(stats.get("subscriberCount", 0))
        view_count  = int(stats.get("viewCount", 0))
        video_count = max(1, int(stats.get("videoCount", 1)))
        avg_views   = view_count // video_count

        posting_frequency = "unknown"
        published_at = snippet.get("publishedAt")
        if published_at:
            try:
                created = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                age_days = max(1, (datetime.now(timezone.utc) - created).days)
                per_week = video_count / age_days * 7
                posting_frequency = f"{per_week:.1f} videos/week"
            except ValueError:
                pass

        return {
            "subscriber_count":    subscriber_count,
            "avg_views_per_video": avg_views,
            "posting_frequency":   posting_frequency,
        }

    def _top_videos(self, channel_id: str) -> Tuple[List[Dict], List[str]]:
        search_params = {
            "part": "snippet", "channelId": channel_id, "type": "video",
            "order": "viewCount", "maxResults": _TOP_VIDEOS_PER_COMPETITOR,
            "key": self._api_key,
        }
        resp = requests.get(f"{_API_BASE}/search", params=search_params, timeout=20)
        if resp.status_code != 200:
            return [], []

        video_ids: List[str] = []
        titles: Dict[str, str] = {}
        for item in resp.json().get("items", []):
            vid = item.get("id", {}).get("videoId")
            title = item.get("snippet", {}).get("title")
            if vid:
                video_ids.append(vid)
                titles[vid] = title or ""

        if not video_ids:
            return [], []

        stats_params = {"part": "statistics", "id": ",".join(video_ids), "key": self._api_key}
        stats_resp = requests.get(f"{_API_BASE}/videos", params=stats_params, timeout=20)
        if stats_resp.status_code != 200:
            return [], []

        top_videos: List[Dict] = []
        for item in stats_resp.json().get("items", []):
            vid = item["id"]
            views = int(item.get("statistics", {}).get("viewCount", 0))
            top_videos.append({"video_id": vid, "title": titles.get(vid, ""), "view_count": views})

        top_videos.sort(key=lambda v: v["view_count"], reverse=True)
        top_hooks = [v["title"] for v in top_videos if v["title"]]
        return top_videos, top_hooks

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _active_competitors(self) -> List[Dict]:
        try:
            return self._db.get_active_competitors()
        except Exception as exc:
            logger.warning("active_competitors_fetch_failed", error=str(exc)[:100])
            return []


_instance: Optional[CompetitorTracker] = None

def get_competitor_tracker() -> CompetitorTracker:
    global _instance
    if _instance is None:
        _instance = CompetitorTracker()
    return _instance


if __name__ == "__main__":
    import json
    result = get_competitor_tracker().run()
    print(json.dumps(result, indent=2, default=str))
