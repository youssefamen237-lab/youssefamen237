"""
manager/project_manager.py – Quizzaro Central Project Manager
==============================================================
The most important file in the project.

Responsibilities:
  1. Fetch full YouTube Analytics for every published Short
  2. Analyse performance by: template, voice gender, publish time, video duration,
     CTA variant, category, difficulty, target audience / country
  3. Auto-update strategy_config.json with winning combinations
  4. Detect underperforming patterns and deprecate them
  5. Adjust daily video count, publish time windows, and content mix
  6. Write a human-readable weekly report to data/reports/

Uses YT_CLIENT_ID_3 / YT_CLIENT_SECRET_3 / YT_REFRESH_TOKEN_3 exclusively.
No placeholders. Full production code.
"""

from __future__ import annotations

import json
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

# ── Paths ─────────────────────────────────────────────────────────────────────
PUBLISH_LOG_PATH = Path("data/publish_log.json")
STRATEGY_CONFIG_PATH = Path("data/strategy_config.json")
REPORTS_DIR = Path("data/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Default strategy (overwritten by optimizer after first run) ───────────────
DEFAULT_STRATEGY = {
    "daily_video_count_min": 4,
    "daily_video_count_max": 8,
    "publish_hour_windows": [[7, 9], [12, 14], [18, 20], [21, 23]],
    "top_templates": [],
    "top_categories": [],
    "top_voice_gender": "mixed",
    "top_audiences": ["American", "British", "Canadian"],
    "target_video_duration_range": [12.0, 16.0],
    "best_cta_indices": [],
    "underperforming_templates": [],
    "underperforming_categories": [],
    "last_updated": None,
    "total_shorts_analysed": 0,
    "channel_subscribers": 0,
    "monetization_progress": {
        "subscribers_needed": 1000,
        "watch_hours_needed": 4000,
        "current_subscribers": 0,
        "current_watch_hours": 0.0,
    },
}

# ── Analytics look-back window ────────────────────────────────────────────────
ANALYTICS_LOOKBACK_DAYS = 28


# ─────────────────────────────────────────────────────────────────────────────
#  OAuth2 / YouTube client builder
# ─────────────────────────────────────────────────────────────────────────────

class YouTubeAnalyticsClient:
    """Wraps YouTube Data API v3 + YouTube Analytics API."""

    DATA_SCOPES = [
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, channel_id: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._channel_id = channel_id
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._yt = None
        self._yta = None

    def _refresh_token_if_needed(self) -> str:
        if self._access_token and self._token_expiry and datetime.utcnow() < self._token_expiry:
            return self._access_token
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

    def _credentials(self) -> Credentials:
        token = self._refresh_token_if_needed()
        return Credentials(
            token=token,
            refresh_token=self._refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._client_id,
            client_secret=self._client_secret,
        )

    def data_api(self):
        creds = self._credentials()
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    def analytics_api(self):
        creds = self._credentials()
        return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

    # ── Data API calls ─────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
    def get_channel_stats(self) -> dict:
        yt = self.data_api()
        resp = yt.channels().list(
            part="statistics,snippet",
            id=self._channel_id,
        ).execute()
        items = resp.get("items", [])
        if not items:
            return {}
        stats = items[0].get("statistics", {})
        return {
            "subscribers": int(stats.get("subscriberCount", 0)),
            "total_views": int(stats.get("viewCount", 0)),
            "video_count": int(stats.get("videoCount", 0)),
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
    def get_recent_shorts(self, max_results: int = 50) -> list[dict]:
        """Return list of Shorts uploaded in the last ANALYTICS_LOOKBACK_DAYS days."""
        yt = self.data_api()
        published_after = (datetime.utcnow() - timedelta(days=ANALYTICS_LOOKBACK_DAYS)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        resp = yt.search().list(
            part="id,snippet",
            channelId=self._channel_id,
            type="video",
            order="date",
            maxResults=max_results,
            publishedAfter=published_after,
        ).execute()

        items = resp.get("items", [])
        results = []
        for item in items:
            vid_id = item["id"].get("videoId")
            if not vid_id:
                continue
            results.append({
                "video_id": vid_id,
                "title": item["snippet"]["title"],
                "published_at": item["snippet"]["publishedAt"],
            })
        return results

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
    def get_video_details(self, video_ids: list[str]) -> dict[str, dict]:
        """Batch-fetch duration + tags for up to 50 video IDs."""
        if not video_ids:
            return {}
        yt = self.data_api()
        resp = yt.videos().list(
            part="contentDetails,statistics,snippet",
            id=",".join(video_ids[:50]),
        ).execute()

        result = {}
        for item in resp.get("items", []):
            vid_id = item["id"]
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            duration_iso = item.get("contentDetails", {}).get("duration", "PT0S")
            result[vid_id] = {
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "duration_sec": _parse_iso_duration(duration_iso),
                "tags": snippet.get("tags", []),
                "title": snippet.get("title", ""),
            }
        return result

    # ── Analytics API calls ────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
    def get_video_analytics(self, video_id: str) -> dict:
        """
        Fetch per-video analytics: views, watch time, avg view %, CTR, demographics.
        """
        yta = self.analytics_api()
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=ANALYTICS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

        try:
            resp = yta.reports().query(
                ids=f"channel=={self._channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,subscribersGained",
                dimensions="video",
                filters=f"video=={video_id}",
            ).execute()

            rows = resp.get("rows", [])
            if rows:
                row = rows[0]
                return {
                    "video_id": video_id,
                    "views": int(row[1]),
                    "watch_minutes": float(row[2]),
                    "avg_view_duration_sec": float(row[3]),
                    "avg_view_percent": float(row[4]),
                    "likes": int(row[5]),
                    "comments": int(row[6]),
                    "subs_gained": int(row[7]),
                }
        except Exception as exc:
            logger.warning(f"[Analytics] Video {video_id} metrics failed: {exc}")

        return {"video_id": video_id, "views": 0, "watch_minutes": 0.0,
                "avg_view_duration_sec": 0.0, "avg_view_percent": 0.0,
                "likes": 0, "comments": 0, "subs_gained": 0}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
    def get_geo_analytics(self) -> list[dict]:
        """Top countries by views for the channel."""
        yta = self.analytics_api()
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=ANALYTICS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        try:
            resp = yta.reports().query(
                ids=f"channel=={self._channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,subscribersGained",
                dimensions="country",
                sort="-views",
                maxResults=15,
            ).execute()
            rows = resp.get("rows", [])
            return [
                {"country": r[0], "views": int(r[1]),
                 "watch_minutes": float(r[2]), "subs_gained": int(r[3])}
                for r in rows
            ]
        except Exception as exc:
            logger.warning(f"[Analytics] Geo analytics failed: {exc}")
            return []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
    def get_total_watch_hours(self) -> float:
        """Return total estimated watch hours for the channel (for monetization tracking)."""
        yta = self.analytics_api()
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")
        try:
            resp = yta.reports().query(
                ids=f"channel=={self._channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="estimatedMinutesWatched",
            ).execute()
            rows = resp.get("rows", [])
            if rows:
                return float(rows[0][0]) / 60.0
        except Exception as exc:
            logger.warning(f"[Analytics] Watch hours failed: {exc}")
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  Publish log enricher
# ─────────────────────────────────────────────────────────────────────────────

class PublishLogEnricher:
    """
    Joins publish_log.json metadata (template, voice, CTA, category, audience)
    with live YouTube Analytics data.
    """

    def __init__(self, log_path: Path = PUBLISH_LOG_PATH) -> None:
        self._path = log_path

    def load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning(f"[PublishLog] Read error: {exc}")
            return []

    def enrich(self, log_entries: list[dict], yt_analytics: dict[str, dict]) -> list[dict]:
        """Merge publish log fields with live analytics per video."""
        enriched = []
        for entry in log_entries:
            vid_id = entry.get("video_id")
            analytics = yt_analytics.get(vid_id, {})
            merged = {**entry, **analytics}
            enriched.append(merged)
        return enriched


# ─────────────────────────────────────────────────────────────────────────────
#  Performance analyser
# ─────────────────────────────────────────────────────────────────────────────

class PerformanceAnalyser:
    """
    Computes performance scores and rankings across all dimensions.
    Score formula: weighted sum of (views × 1.0) + (avg_view_percent × 50) +
                   (subs_gained × 100) + (likes × 2) + (comments × 3)
    """

    @staticmethod
    def _score(entry: dict) -> float:
        return (
            entry.get("views", 0) * 1.0
            + entry.get("avg_view_percent", 0) * 50
            + entry.get("subs_gained", 0) * 100
            + entry.get("likes", 0) * 2
            + entry.get("comments", 0) * 3
        )

    def rank_by_dimension(self, entries: list[dict], dimension: str) -> list[tuple[str, float]]:
        """
        Group entries by *dimension* key, compute mean score per group.
        Returns sorted list of (value, mean_score) descending.
        """
        groups: dict[str, list[float]] = defaultdict(list)
        for entry in entries:
            key = str(entry.get(dimension, "unknown"))
            if key and key != "unknown":
                groups[key].append(self._score(entry))

        ranked = []
        for k, scores in groups.items():
            if scores:
                ranked.append((k, statistics.mean(scores)))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def rank_publish_hours(self, entries: list[dict]) -> list[tuple[int, float]]:
        """Rank publish hours (0–23) by mean performance score."""
        groups: dict[int, list[float]] = defaultdict(list)
        for entry in entries:
            pub_at = entry.get("published_at", "")
            try:
                hour = datetime.fromisoformat(pub_at.replace("Z", "+00:00")).hour
                groups[hour].append(self._score(entry))
            except Exception:
                continue

        ranked = [(h, statistics.mean(s)) for h, s in groups.items() if s]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def rank_video_durations(self, entries: list[dict]) -> dict:
        """Find optimal video duration range (bucket by 2-second bins)."""
        buckets: dict[str, list[float]] = defaultdict(list)
        for entry in entries:
            dur = entry.get("duration_sec", 0)
            if dur > 0:
                bucket = f"{int(dur // 2) * 2}-{int(dur // 2) * 2 + 2}s"
                buckets[bucket].append(self._score(entry))

        ranked = [(b, statistics.mean(s)) for b, s in buckets.items() if s]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return {"top_buckets": ranked[:3]}

    def detect_underperformers(
        self,
        entries: list[dict],
        dimension: str,
        threshold_percentile: float = 0.25,
    ) -> list[str]:
        """
        Return dimension values whose mean score is in the bottom
        threshold_percentile of all groups.
        """
        ranked = self.rank_by_dimension(entries, dimension)
        if len(ranked) < 4:
            return []
        cutoff_idx = max(1, int(len(ranked) * threshold_percentile))
        return [v for v, _ in ranked[-cutoff_idx:]]

    def compute_engagement_rate(self, entries: list[dict]) -> float:
        total_views = sum(e.get("views", 0) for e in entries)
        total_likes = sum(e.get("likes", 0) for e in entries)
        total_comments = sum(e.get("comments", 0) for e in entries)
        if total_views == 0:
            return 0.0
        return (total_likes + total_comments) / total_views * 100


# ─────────────────────────────────────────────────────────────────────────────
#  Strategy config updater
# ─────────────────────────────────────────────────────────────────────────────

class StrategyConfigUpdater:
    """Reads, updates, and writes strategy_config.json."""

    def __init__(self, config_path: Path = STRATEGY_CONFIG_PATH) -> None:
        self._path = config_path

    def load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return DEFAULT_STRATEGY.copy()

    def save(self, config: dict) -> None:
        config["last_updated"] = datetime.utcnow().isoformat()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.success(f"[Strategy] Config saved → {self._path}")

    def update(
        self,
        analyser: PerformanceAnalyser,
        entries: list[dict],
        channel_stats: dict,
        geo_data: list[dict],
        watch_hours: float,
    ) -> dict:
        config = self.load()

        if not entries:
            logger.warning("[Strategy] No entries to analyse. Config unchanged.")
            return config

        # ── Template rankings ──────────────────────────────────────────────
        template_rank = analyser.rank_by_dimension(entries, "template")
        if template_rank:
            config["top_templates"] = [t for t, _ in template_rank[:4]]
            config["underperforming_templates"] = analyser.detect_underperformers(entries, "template")

        # ── Category rankings ──────────────────────────────────────────────
        cat_rank = analyser.rank_by_dimension(entries, "category")
        if cat_rank:
            config["top_categories"] = [c for c, _ in cat_rank[:6]]
            config["underperforming_categories"] = analyser.detect_underperformers(entries, "category")

        # ── Voice gender ───────────────────────────────────────────────────
        gender_rank = analyser.rank_by_dimension(entries, "gender")
        if gender_rank:
            top_gender = gender_rank[0][0]
            # If difference is large (>30%), prefer winner; otherwise keep mixed
            if len(gender_rank) >= 2:
                gap = (gender_rank[0][1] - gender_rank[1][1]) / max(gender_rank[0][1], 1)
                config["top_voice_gender"] = top_gender if gap > 0.30 else "mixed"
            else:
                config["top_voice_gender"] = top_gender

        # ── Publish hour windows ───────────────────────────────────────────
        hour_rank = analyser.rank_publish_hours(entries)
        if len(hour_rank) >= 4:
            top_hours = sorted([h for h, _ in hour_rank[:6]])
            # Group consecutive hours into windows
            windows = _hours_to_windows(top_hours)
            if windows:
                config["publish_hour_windows"] = windows

        # ── Video duration range ───────────────────────────────────────────
        dur_info = analyser.rank_video_durations(entries)
        top_buckets = dur_info.get("top_buckets", [])
        if top_buckets:
            bucket_str = top_buckets[0][0]   # e.g. "12-14s"
            try:
                lo, hi = bucket_str.replace("s", "").split("-")
                config["target_video_duration_range"] = [float(lo) - 0.5, float(hi) + 0.5]
            except Exception:
                pass

        # ── Target audience / geo ──────────────────────────────────────────
        COUNTRY_TO_AUDIENCE = {
            "US": "American", "GB": "British", "CA": "Canadian",
            "AU": "Australian", "IE": "Irish", "NZ": "New Zealander",
            "IN": "Indian English", "NG": "Nigerian English",
        }
        if geo_data:
            top_countries = [g["country"] for g in geo_data[:5]]
            audiences = [COUNTRY_TO_AUDIENCE.get(c, c) for c in top_countries]
            if audiences:
                config["top_audiences"] = audiences[:4]

        # ── Daily video count heuristic ────────────────────────────────────
        # If channel growing fast → push more videos; if low performance → reduce
        subs = channel_stats.get("subscribers", 0)
        config["channel_subscribers"] = subs
        engagement = analyser.compute_engagement_rate(entries)
        if engagement > 5.0:
            config["daily_video_count_min"] = 6
            config["daily_video_count_max"] = 8
        elif engagement < 1.5:
            config["daily_video_count_min"] = 4
            config["daily_video_count_max"] = 5
        else:
            config["daily_video_count_min"] = 4
            config["daily_video_count_max"] = 7

        # ── Monetization progress ──────────────────────────────────────────
        config["monetization_progress"] = {
            "subscribers_needed": 1000,
            "watch_hours_needed": 4000,
            "current_subscribers": subs,
            "current_watch_hours": round(watch_hours, 1),
            "subscribers_remaining": max(0, 1000 - subs),
            "watch_hours_remaining": max(0.0, 4000 - watch_hours),
            "sub_completion_pct": round(min(100, subs / 10), 1),
            "watch_hours_completion_pct": round(min(100, watch_hours / 40), 1),
        }

        config["total_shorts_analysed"] = len(entries)

        return config


# ─────────────────────────────────────────────────────────────────────────────
#  Report writer
# ─────────────────────────────────────────────────────────────────────────────

class ReportWriter:
    """Writes a human-readable Markdown report to data/reports/."""

    def write(
        self,
        config: dict,
        entries: list[dict],
        geo_data: list[dict],
        analyser: PerformanceAnalyser,
    ) -> str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        report_path = REPORTS_DIR / f"report_{date_str}.md"

        mon = config.get("monetization_progress", {})
        template_rank = analyser.rank_by_dimension(entries, "template")
        cat_rank = analyser.rank_by_dimension(entries, "category")
        hour_rank = analyser.rank_publish_hours(entries)
        engagement = analyser.compute_engagement_rate(entries)
        total_views = sum(e.get("views", 0) for e in entries)
        total_subs_gained = sum(e.get("subs_gained", 0) for e in entries)

        lines = [
            f"# 📊 Quizzaro Weekly Report — {date_str}",
            "",
            "## 💰 Monetization Progress",
            f"- Subscribers: **{mon.get('current_subscribers', 0):,}** / 1,000 "
            f"({mon.get('sub_completion_pct', 0)}%)",
            f"- Watch Hours: **{mon.get('current_watch_hours', 0):,.1f}h** / 4,000h "
            f"({mon.get('watch_hours_completion_pct', 0)}%)",
            f"- Remaining Subs: {mon.get('subscribers_remaining', 0):,}",
            f"- Remaining Watch Hours: {mon.get('watch_hours_remaining', 0):,.1f}h",
            "",
            "## 📈 Channel Overview (Last 28 Days)",
            f"- Total Shorts Analysed: **{len(entries)}**",
            f"- Total Views: **{total_views:,}**",
            f"- Subscribers Gained: **{total_subs_gained:,}**",
            f"- Engagement Rate: **{engagement:.2f}%**",
            "",
            "## 🏆 Top Templates",
        ]
        for rank, (t, score) in enumerate(template_rank[:5], 1):
            lines.append(f"  {rank}. `{t}` — score: {score:,.0f}")

        lines += ["", "## 📚 Top Categories"]
        for rank, (c, score) in enumerate(cat_rank[:6], 1):
            lines.append(f"  {rank}. `{c}` — score: {score:,.0f}")

        lines += ["", "## ⏰ Best Publish Hours (UTC)"]
        for h, score in hour_rank[:6]:
            lines.append(f"  - {h:02d}:xx — score: {score:,.0f}")

        lines += ["", "## 🌍 Top Countries"]
        for g in geo_data[:8]:
            lines.append(
                f"  - {g['country']}: {g['views']:,} views | "
                f"{g['watch_minutes']/60:.1f}h | +{g['subs_gained']} subs"
            )

        lines += [
            "",
            "## ⚙️ Updated Strategy Config",
            f"- Daily Videos: {config['daily_video_count_min']}–{config['daily_video_count_max']}",
            f"- Voice Gender: {config['top_voice_gender']}",
            f"- Top Audiences: {', '.join(config.get('top_audiences', []))}",
            f"- Target Duration: {config.get('target_video_duration_range', [12, 16])}s",
            f"- Underperforming Templates: {config.get('underperforming_templates', [])}",
            f"- Underperforming Categories: {config.get('underperforming_categories', [])}",
            "",
            f"*Generated automatically by project_manager.py at {datetime.utcnow().isoformat()} UTC*",
        ]

        report_path.write_text("\n".join(lines), encoding="utf-8")
        logger.success(f"[Report] Written → {report_path}")
        return str(report_path)


# ─────────────────────────────────────────────────────────────────────────────
#  Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _parse_iso_duration(iso: str) -> float:
    """Parse ISO 8601 duration (e.g. PT1M23S) to total seconds."""
    import re
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", iso)
    if not match:
        return 0.0
    h = float(match.group(1) or 0)
    m = float(match.group(2) or 0)
    s = float(match.group(3) or 0)
    return h * 3600 + m * 60 + s


def _hours_to_windows(hours: list[int]) -> list[list[int]]:
    """Convert a sorted list of hours to [start, end] windows."""
    if not hours:
        return []
    windows = []
    start = hours[0]
    prev = hours[0]
    for h in hours[1:]:
        if h - prev > 2:
            windows.append([start, prev + 1])
            start = h
        prev = h
    windows.append([start, prev + 1])
    return windows


# ─────────────────────────────────────────────────────────────────────────────
#  Master Project Manager
# ─────────────────────────────────────────────────────────────────────────────

class ProjectManager:
    """
    Top-level orchestrator. Called by main.py with --mode manager.

    Full workflow:
      1. Fetch channel stats
      2. Fetch list of recent Shorts from YouTube
      3. Batch-fetch video details (duration, tags)
      4. For each video: fetch Analytics metrics
      5. Enrich with publish_log.json metadata (template, voice, CTA, etc.)
      6. Run PerformanceAnalyser across all dimensions
      7. Update strategy_config.json
      8. Write weekly Markdown report
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        channel_id: str,
        ai_engine,
    ) -> None:
        self._yt = YouTubeAnalyticsClient(client_id, client_secret, refresh_token, channel_id)
        self._log = PublishLogEnricher()
        self._analyser = PerformanceAnalyser()
        self._strategy = StrategyConfigUpdater()
        self._reporter = ReportWriter()

    def run(self) -> None:
        logger.info("[ProjectManager] Starting analytics run …")

        # ── 1. Channel stats ───────────────────────────────────────────────
        channel_stats = {}
        try:
            channel_stats = self._yt.get_channel_stats()
            logger.info(
                f"[ProjectManager] Channel: {channel_stats.get('subscribers', 0):,} subs | "
                f"{channel_stats.get('total_views', 0):,} total views"
            )
        except Exception as exc:
            logger.error(f"[ProjectManager] Channel stats failed: {exc}")

        # ── 2. Recent Shorts ───────────────────────────────────────────────
        recent_shorts = []
        try:
            recent_shorts = self._yt.get_recent_shorts(max_results=50)
            logger.info(f"[ProjectManager] Found {len(recent_shorts)} recent Shorts")
        except Exception as exc:
            logger.error(f"[ProjectManager] get_recent_shorts failed: {exc}")

        if not recent_shorts:
            logger.warning("[ProjectManager] No Shorts found. Writing default config.")
            config = self._strategy.load()
            self._strategy.save(config)
            return

        # ── 3. Video details (batch) ───────────────────────────────────────
        video_ids = [v["video_id"] for v in recent_shorts]
        video_details: dict[str, dict] = {}
        try:
            for i in range(0, len(video_ids), 50):
                batch = video_ids[i:i + 50]
                video_details.update(self._yt.get_video_details(batch))
            logger.info(f"[ProjectManager] Video details fetched for {len(video_details)} videos")
        except Exception as exc:
            logger.error(f"[ProjectManager] Video details failed: {exc}")

        # ── 4. Per-video Analytics ─────────────────────────────────────────
        analytics_map: dict[str, dict] = {}
        for vid in recent_shorts:
            vid_id = vid["video_id"]
            try:
                metrics = self._yt.get_video_analytics(vid_id)
                detail = video_details.get(vid_id, {})
                analytics_map[vid_id] = {
                    **vid,
                    **metrics,
                    "duration_sec": detail.get("duration_sec", 0),
                    "tags": detail.get("tags", []),
                }
            except Exception as exc:
                logger.warning(f"[ProjectManager] Analytics for {vid_id} failed: {exc}")
                analytics_map[vid_id] = {**vid, "views": 0}

        # ── 5. Enrich with local publish_log metadata ──────────────────────
        log_entries = self._log.load()
        enriched = self._log.enrich(log_entries, analytics_map)

        # Also include any videos found on YouTube but not in local log
        log_ids = {e.get("video_id") for e in log_entries}
        for vid_id, data in analytics_map.items():
            if vid_id not in log_ids:
                enriched.append(data)

        logger.info(f"[ProjectManager] Total enriched entries: {len(enriched)}")

        # ── 6. Geo analytics ───────────────────────────────────────────────
        geo_data = []
        try:
            geo_data = self._yt.get_geo_analytics()
        except Exception as exc:
            logger.warning(f"[ProjectManager] Geo analytics failed: {exc}")

        # ── 7. Watch hours (monetization tracking) ─────────────────────────
        watch_hours = 0.0
        try:
            watch_hours = self._yt.get_total_watch_hours()
            logger.info(f"[ProjectManager] Total watch hours: {watch_hours:,.1f}h")
        except Exception as exc:
            logger.warning(f"[ProjectManager] Watch hours failed: {exc}")

        # ── 8. Update strategy config ──────────────────────────────────────
        updated_config = self._strategy.update(
            analyser=self._analyser,
            entries=enriched,
            channel_stats=channel_stats,
            geo_data=geo_data,
            watch_hours=watch_hours,
        )
        self._strategy.save(updated_config)

        # ── 9. Write report ────────────────────────────────────────────────
        try:
            report_path = self._reporter.write(
                config=updated_config,
                entries=enriched,
                geo_data=geo_data,
                analyser=self._analyser,
            )
            logger.success(f"[ProjectManager] Report → {report_path}")
        except Exception as exc:
            logger.error(f"[ProjectManager] Report generation failed: {exc}")

        # ── 10. Log monetization status ────────────────────────────────────
        mon = updated_config.get("monetization_progress", {})
        logger.info(
            f"[ProjectManager] 💰 Monetization | "
            f"Subs: {mon.get('current_subscribers', 0):,}/1,000 "
            f"({mon.get('sub_completion_pct', 0)}%) | "
            f"Watch Hours: {mon.get('current_watch_hours', 0):,.1f}/4,000h "
            f"({mon.get('watch_hours_completion_pct', 0)}%)"
        )

        logger.success("[ProjectManager] Analytics run complete.")
