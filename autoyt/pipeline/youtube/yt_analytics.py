\
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from autoyt.pipeline.youtube.auth import get_credentials
from autoyt.utils.logging_utils import get_logger

log = get_logger("autoyt.youtube.analytics")

SCOPES_ANALYTICS = ["https://www.googleapis.com/auth/yt-analytics.readonly"]


def _build(profile: int):
    creds = get_credentials(profile, scopes=SCOPES_ANALYTICS)
    return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)


def get_top_countries(
    profile: int,
    start_date: dt.date,
    end_date: dt.date,
    max_rows: int = 10,
) -> List[Tuple[str, int, float]]:
    """
    Returns list of (country_code, views, estimated_minutes_watched)
    """
    try:
        yt = _build(profile)
        req = yt.reports().query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            metrics="views,estimatedMinutesWatched",
            dimensions="country",
            sort="-estimatedMinutesWatched",
            maxResults=max_rows,
        )
        resp = req.execute()
        rows = resp.get("rows") or []
        out: List[Tuple[str, int, float]] = []
        for row in rows:
            # row: [country, views, minutes]
            try:
                out.append((str(row[0]), int(row[1]), float(row[2])))
            except Exception:
                continue
        return out
    except HttpError as e:
        log.warning(f"YouTube Analytics API failed (country report): {e}")
        return []
    except Exception as e:
        log.warning(f"YouTube Analytics API failed (country report): {e}")
        return []
