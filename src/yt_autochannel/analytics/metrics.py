from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class VideoMetrics:
    views: int = 0
    likes: int = 0
    comments: int = 0
    favorites: int = 0
    # Optional fields (Analytics API) - may remain None
    avg_view_duration_s: Optional[float] = None
    engaged_views: Optional[int] = None
    subs_gained: Optional[int] = None


def composite_score(m: VideoMetrics) -> float:
    # Conservative score that works without Analytics API
    # Emphasize engagement rate-ish signals without dividing by unknown impressions
    score = 0.0
    score += m.views * 1.0
    score += m.likes * 20.0
    score += m.comments * 30.0
    if m.subs_gained is not None:
        score += m.subs_gained * 200.0
    if m.avg_view_duration_s is not None:
        score += m.avg_view_duration_s * 5.0
    return score
