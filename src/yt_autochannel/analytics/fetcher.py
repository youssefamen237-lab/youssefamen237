from __future__ import annotations

from typing import Dict, List

from googleapiclient.errors import HttpError

from ..providers.youtube_uploader import YouTubeUploader
from .metrics import VideoMetrics


class YouTubeStatsFetcher:
    def __init__(self, uploader: YouTubeUploader):
        self.uploader = uploader

    def fetch_basic_stats(self, video_ids: List[str]) -> Dict[str, VideoMetrics]:
        out: Dict[str, VideoMetrics] = {}
        if not video_ids:
            return out
        # Data API allows up to 50 ids per request
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i : i + 50]
            try:
                resp = (
                    self.uploader.service.videos()
                    .list(part="statistics", id=",".join(chunk), maxResults=len(chunk))
                    .execute()
                )
            except HttpError:
                continue
            for item in resp.get("items", []):
                vid = item.get("id")
                stats = item.get("statistics", {})
                out[vid] = VideoMetrics(
                    views=int(stats.get("viewCount", 0)),
                    likes=int(stats.get("likeCount", 0)),
                    comments=int(stats.get("commentCount", 0)),
                    favorites=int(stats.get("favoriteCount", 0)),
                )
        return out


def composite_score(m: VideoMetrics) -> float:
    # Simple fallback score (no Analytics API):
    # reward engagement (likes/comments) and raw views.
    return float(m.views) + 20.0 * float(m.likes) + 40.0 * float(m.comments)
