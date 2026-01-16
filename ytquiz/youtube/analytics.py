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
