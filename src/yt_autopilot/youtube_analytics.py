\
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from googleapiclient.discovery import build

from .youtube_auth import OAuthCandidate, pick_working_credentials

logger = logging.getLogger(__name__)


ANALYTICS_SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def _daterange(lookback_days: int) -> Tuple[str, str]:
    end = (datetime.now(timezone.utc).date() - timedelta(days=1))
    start = end - timedelta(days=lookback_days - 1)
    return start.isoformat(), end.isoformat()


def build_analytics_client(oauth_candidates: List[OAuthCandidate]):
    creds = pick_working_credentials(oauth_candidates, scopes=ANALYTICS_SCOPES)
    return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)


def query_report(
    yt_analytics,
    *,
    start_date: str,
    end_date: str,
    metrics: str,
    dimensions: Optional[str] = None,
    filters: Optional[str] = None,
    sort: Optional[str] = None,
    max_results: int = 200,
) -> Dict[str, Any]:
    req = yt_analytics.reports().query(
        ids="channel==MINE",
        startDate=start_date,
        endDate=end_date,
        metrics=metrics,
        dimensions=dimensions,
        filters=filters,
        sort=sort,
        maxResults=max_results,
    )
    return req.execute()


def get_hourly_views(yt_analytics, lookback_days: int) -> Dict[int, float]:
    start, end = _daterange(lookback_days)
    doc = query_report(
        yt_analytics,
        start_date=start,
        end_date=end,
        metrics="views,estimatedMinutesWatched",
        dimensions="hour",
        sort="-views",
        max_results=200,
    )
    rows = doc.get("rows") or []
    out: Dict[int, float] = {}
    for r in rows:
        try:
            hour = int(r[0])
            views = float(r[1])
            out[hour] = out.get(hour, 0.0) + views
        except Exception:
            continue
    return out


def get_video_metrics(yt_analytics, video_id: str, lookback_days: int) -> Optional[Dict[str, float]]:
    start, end = _daterange(lookback_days)
    try:
        doc = query_report(
            yt_analytics,
            start_date=start,
            end_date=end,
            metrics="views,likes,comments,shares,estimatedMinutesWatched,averageViewDuration,subscribersGained",
            dimensions=None,
            filters=f"video=={video_id}",
            max_results=1,
        )
        rows = doc.get("rows") or []
        if not rows:
            return None
        r = rows[0]
        # metrics order: views,likes,comments,shares,estimatedMinutesWatched,averageViewDuration,subscribersGained
        return {
            "views": float(r[0]),
            "likes": float(r[1]),
            "comments": float(r[2]),
            "shares": float(r[3]),
            "estimatedMinutesWatched": float(r[4]),
            "averageViewDuration": float(r[5]),
            "subscribersGained": float(r[6]),
        }
    except Exception as e:
        logger.warning("video metrics failed video=%s err=%s", video_id, e)
        return None
