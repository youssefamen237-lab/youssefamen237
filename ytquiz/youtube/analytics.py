from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ytquiz.log import Log
from ytquiz.utils import utc_date_str


METRICS = [
    "views",
    "engagedViews",
    "likes",
    "comments",
    "shares",
    "subscribersGained",
    "subscribersLost",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
]


def fetch_video_metrics(
    *,
    analytics: Any,
    youtube: Any,
    channel_id: str,
    video_id: str,
    publish_dt: datetime,
    lookback_days: int,
    log: Log,
) -> dict[str, float] | None:
    # 1) Try Analytics API first (best metrics)
    m = _fetch_from_analytics(
        analytics=analytics,
        channel_id=channel_id,
        video_id=video_id,
        publish_dt=publish_dt,
        lookback_days=lookback_days,
        log=log,
    )
    if m:
        m["metricsSource"] = 1.0  # 1 = analytics
        return m

    # 2) Fallback: YouTube Data API statistics (works even without yt-analytics scopes)
    m2 = _fetch_from_data_api(youtube=youtube, video_id=video_id, log=log)
    if m2:
        m2["metricsSource"] = 2.0  # 2 = data api
        return m2

    return None


def _fetch_from_analytics(
    *,
    analytics: Any,
    channel_id: str,
    video_id: str,
    publish_dt: datetime,
    lookback_days: int,
    log: Log,
) -> dict[str, float] | None:
    today = datetime.now(tz=publish_dt.tzinfo)
    start = max(publish_dt, today - timedelta(days=max(1, lookback_days)))
    start_s = utc_date_str(start)
    end_s = utc_date_str(today)

    try:
        resp = (
            analytics.reports()
            .query(
                ids=f"channel=={channel_id}",
                startDate=start_s,
                endDate=end_s,
                metrics=",".join(METRICS),
                filters=f"video=={video_id}",
            )
            .execute()
        )
    except Exception as e:
        log.warn(f"Analytics query failed for {video_id}: {e}")
        return None

    rows = resp.get("rows") or []
    if not rows:
        return None

    headers = resp.get("columnHeaders") or []
    values = rows[0]
    out: dict[str, float] = {}
    for i, h in enumerate(headers):
        name = h.get("name")
        if not name:
            continue
        try:
            out[str(name)] = float(values[i])
        except Exception:
            continue
    return out


def _fetch_from_data_api(*, youtube: Any, video_id: str, log: Log) -> dict[str, float] | None:
    try:
        resp = youtube.videos().list(part="statistics", id=video_id).execute()
        items = resp.get("items") or []
        if not items:
            return None
        stats = (items[0].get("statistics") or {}) if isinstance(items[0], dict) else {}
        views = float(stats.get("viewCount") or 0.0)
        likes = float(stats.get("likeCount") or 0.0)
        comments = float(stats.get("commentCount") or 0.0)
        # shares/subscribers/retention not available here
        return {
            "views": views,
            "likes": likes,
            "comments": comments,
        }
    except Exception as e:
        log.warn(f"Data API stats failed for {video_id}: {e}")
        return None
