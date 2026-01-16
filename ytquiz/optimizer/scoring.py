from __future__ import annotations

from typing import Any

from ytquiz.utils import clamp


def compute_score(metrics: dict[str, Any], video_length_seconds: float) -> float | None:
    try:
        views = float(metrics.get("views") or 0.0)
        if views <= 0:
            return None

        avd = float(metrics.get("averageViewDuration") or 0.0)
        engaged = float(metrics.get("engagedViews") or 0.0)
        likes = float(metrics.get("likes") or 0.0)
        comments = float(metrics.get("comments") or 0.0)
        shares = float(metrics.get("shares") or 0.0)
        subs_g = float(metrics.get("subscribersGained") or 0.0)

        vlen = max(1.0, float(video_length_seconds or 1.0))
        retention = clamp(avd / vlen, 0.0, 1.0)

        engaged_ratio = clamp(engaged / views, 0.0, 1.0)

        engagement = (likes + comments + shares) / max(1.0, views)
        engagement_scaled = clamp(engagement / 0.05, 0.0, 1.0)

        subs_ratio = subs_g / max(1.0, views)
        subs_scaled = clamp(subs_ratio / 0.01, 0.0, 1.0)

        score = 0.62 * retention + 0.18 * engaged_ratio + 0.12 * engagement_scaled + 0.08 * subs_scaled
        return float(clamp(score, 0.0, 1.0))
    except Exception:
        return None
