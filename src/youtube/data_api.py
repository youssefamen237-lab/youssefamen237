from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

log = logging.getLogger("yt_data_api")


def build_public_client():
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing YOUTUBE_API_KEY")
    return build("youtube", "v3", developerKey=key, cache_discovery=False)


def fetch_videos_snippet_statistics(video_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not video_ids:
        return {}
    yt = build_public_client()
    out: Dict[str, Dict[str, Any]] = {}
    # Max 50 per request
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        try:
            resp = yt.videos().list(part="snippet,statistics,status", id=",".join(chunk)).execute()
        except HttpError as e:
            log.warning("videos.list failed: %s", e)
            continue
        for it in resp.get("items", []):
            vid = it.get("id")
            if not vid:
                continue
            out[str(vid)] = it
    return out
