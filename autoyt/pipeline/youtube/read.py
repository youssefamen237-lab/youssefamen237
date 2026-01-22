\
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from autoyt.pipeline.youtube.auth import get_credentials
from autoyt.utils.logging_utils import get_logger

log = get_logger("autoyt.youtube.read")

SCOPES_READONLY = ["https://www.googleapis.com/auth/youtube.readonly"]


def _build_youtube(profile: int):
    creds = get_credentials(profile, scopes=SCOPES_READONLY)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def fetch_video_stats(profile: int, video_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Returns mapping video_id -> {snippet, statistics, contentDetails}.
    """
    youtube = _build_youtube(profile)
    out: Dict[str, Dict[str, Any]] = {}
    # API allows up to 50 ids per call
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        try:
            req = youtube.videos().list(part="snippet,statistics,contentDetails", id=",".join(chunk))
            resp = req.execute()
            for item in resp.get("items", []) or []:
                vid = item.get("id")
                if vid:
                    out[str(vid)] = item
        except HttpError as e:
            log.warning(f"fetch_video_stats failed: {e}")
            continue
    return out
