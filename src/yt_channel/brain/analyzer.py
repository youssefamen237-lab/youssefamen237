from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..state.db import StateDB
from ..youtube.analytics import YouTubeMetricsFetcher
from .bandit import BetaBandit

logger = logging.getLogger(__name__)


def _parse_iso(dt: Optional[str]) -> Optional[datetime]:
    if not dt:
        return None
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def compute_score(*, metrics: Dict[str, Any], published_at: Optional[str]) -> float:
    """Composite score from available metrics.

    Uses views, likes, comments, and time-normalized views.
    """
    views = float(metrics.get("views", 0) or 0)
    likes = float(metrics.get("likes", 0) or 0)
    comments = float(metrics.get("comments", 0) or 0)

    age_hours = 24.0
    dt = _parse_iso(published_at)
    if dt:
        delta = datetime.now(timezone.utc) - dt
        age_hours = max(delta.total_seconds() / 3600.0, 1.0)

    vph = views / age_hours
    like_rate = likes / max(views, 1.0)
    comment_rate = comments / max(views, 1.0)

    # Scale to keep values reasonable
    score = vph * 0.7 + (like_rate * 100.0) * 0.2 + (comment_rate * 100.0) * 0.1
    # If Analytics API metrics exist, add them
    if metrics.get("ya_avg_view_percentage") is not None:
        avp = float(metrics.get("ya_avg_view_percentage", 0) or 0)
        score += avp * 0.15
    if metrics.get("ya_avg_view_duration") is not None:
        avd = float(metrics.get("ya_avg_view_duration", 0) or 0)
        score += min(avd, 120.0) * 0.02
    return float(score)


class Analyzer:
    def __init__(self, *, db: StateDB, metrics: YouTubeMetricsFetcher, bandit: BetaBandit) -> None:
        self.db = db
        self.metrics = metrics
        self.bandit = bandit

    def refresh_metrics(self, *, days_back: int = 14) -> Dict[str, Dict[str, Any]]:
        recents = self.db.list_recent_videos(days_back=days_back)
        ids = [r.get("video_id") for r in recents if r.get("video_id")]
        ids = [str(x) for x in ids if x]
        basic = self.metrics.fetch_basic_stats(ids)
        ya = self.metrics.fetch_analytics_last_days(days_back=30)

        merged: Dict[str, Dict[str, Any]] = {}
        for vid, m in basic.items():
            mm = dict(m)
            if vid in ya:
                mm.update(ya[vid])
            merged[vid] = mm
        for vid, m in merged.items():
            try:
                self.db.update_video_metrics(video_id=vid, metrics=m)
            except Exception:
                continue
        return merged

    def update_bandit_from_recent(self, *, days_back: int = 14) -> None:
        recents = self.db.list_recent_videos(days_back=days_back)
        scored: List[Tuple[str, float, Dict[str, Any]]] = []

        for r in recents:
            vid = r.get("video_id")
            if not vid:
                continue
            metrics_json = r.get("metrics_json")
            if not metrics_json:
                continue
            try:
                metrics = json.loads(metrics_json)
            except Exception:
                continue
            score = compute_score(metrics=metrics, published_at=metrics.get("publishedAt"))
            scored.append((str(vid), score, r))

        if not scored:
            return

        # Success threshold by kind (median)
        by_kind: Dict[str, List[float]] = {}
        for _, s, r in scored:
            k = str(r.get("kind") or "")
            by_kind.setdefault(k, []).append(float(s))
        medians: Dict[str, float] = {}
        for k, arr in by_kind.items():
            arr = sorted(arr)
            medians[k] = arr[len(arr) // 2]

        for _, s, r in scored:
            kind = str(r.get("kind") or "")
            success = float(s) >= medians.get(kind, float("inf"))

            template_id = str(r.get("template_id") or "")
            topic = str(r.get("topic") or "")
            voice = str(r.get("voice_gender") or "")

            try:
                meta = json.loads(r.get("metadata_json") or "{}")
            except Exception:
                meta = {}

            time_slot = str(meta.get("slot") or "")
            music_on = "music_on" if bool(meta.get("with_music")) else "music_off"

            if template_id:
                self.bandit.update(arm_type="template", arm_value=template_id, success=success)
            if topic:
                self.bandit.update(arm_type="topic", arm_value=topic, success=success)
            if voice:
                self.bandit.update(arm_type="voice", arm_value=voice, success=success)
            if time_slot:
                self.bandit.update(arm_type="time_slot", arm_value=time_slot, success=success)
            self.bandit.update(arm_type="music", arm_value=music_on, success=success)

    def voice_winner(self, *, min_shorts: int = 28) -> Optional[str]:
        # Determine winner after first week using scored shorts.
        recents = self.db.list_recent_videos(days_back=30)
        shorts = [r for r in recents if r.get("kind") == "short" and r.get("metrics_json")]
        if len(shorts) < min_shorts:
            return None

        scores_by_voice: Dict[str, List[float]] = {"female": [], "male": []}
        for r in shorts:
            voice = str(r.get("voice_gender") or "").lower()
            if voice not in scores_by_voice:
                continue
            try:
                metrics = json.loads(r.get("metrics_json") or "{}")
            except Exception:
                continue
            score = compute_score(metrics=metrics, published_at=metrics.get("publishedAt"))
            scores_by_voice[voice].append(score)

        def avg(xs: List[float]) -> float:
            return sum(xs) / max(len(xs), 1)

        f_avg = avg(scores_by_voice["female"])
        m_avg = avg(scores_by_voice["male"])
        if f_avg == 0 and m_avg == 0:
            return None
        return "female" if f_avg >= m_avg else "male"
