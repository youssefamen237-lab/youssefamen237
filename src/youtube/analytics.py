from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .auth import get_credentials

log = logging.getLogger("yt_analytics")

YT_ANALYTICS_READONLY_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"


def build_analytics_client():
    creds = get_credentials([YT_ANALYTICS_READONLY_SCOPE])
    return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)


def query_report(
    *,
    channel_id: str,
    start_date: date,
    end_date: date,
    metrics: str,
    dimensions: Optional[str] = None,
    filters: Optional[str] = None,
    sort: Optional[str] = None,
    max_results: int = 200,
) -> Dict[str, Any]:
    yt = build_analytics_client()
    params: Dict[str, Any] = {
        "ids": f"channel=={channel_id}",
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "metrics": metrics,
        "maxResults": max_results,
    }
    if dimensions:
        params["dimensions"] = dimensions
    if filters:
        params["filters"] = filters
    if sort:
        params["sort"] = sort
    try:
        return yt.reports().query(**params).execute()
    except HttpError as e:
        log.warning("analytics query failed: %s", e)
        raise
