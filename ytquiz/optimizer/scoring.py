from __future__ import annotations

import math
from typing import Any

from ytquiz.utils import clamp


def compute_score(metrics: dict[str, Any], video_length_seconds: float) -> float | None:
    try:
        views = float(metrics.get("views") or 0.0)
        if views <= 0:
            return None

        vlen = max(1.0, float(video_length_seconds or 1.0))

        terms: list[float] = []
        weights: list[float] = []

        # Retention (best) - Analytics only
        avd = metrics.get("averageViewDuration")
        if avd is not None:
            try:
                avd_f = float(avd)
                if avd_f > 0:
                    retention = clamp(avd_f / vlen, 0.0, 1.0)
                    terms.append(retention)
                    weights.append(0.55)
            except Exception:
                pass

        avp = metrics.get("averageViewPercentage")
        if avp is not None:
            try:
                avp_f = float(avp)
                # Some responses are 0..100, normalize if needed
                if avp_f > 1.0:
                    avp_f = avp_f / 100.0
                terms.append(clamp(avp_f, 0.0, 1.0))
                weights.append(0.10)
            except Exception:
                pass

        engaged = metrics.get("engagedViews")
        if engaged is not None:
            try:
                engaged_f = float(engaged)
                if engaged_f > 0:
                    engaged_ratio = clamp(engaged_f / views, 0.0, 1.0)
                    terms.append(engaged_ratio)
                    weights.append(0.12)
            except Exception:
                pass

        likes = float(metrics.get("likes") or 0.0)
        comments = float(metrics.get("comments") or 0.0)
        shares = float(metrics.get("shares") or 0.0)

        # Engagement proxy (Data API or Analytics)
        engagement_rate = (likes + 2.0 * comments + 2.0 * shares) / max(1.0, views)
        engagement_scaled = clamp(engagement_rate / 0.05, 0.0, 1.0)
        terms.append(engagement_scaled)
        weights.append(0.18)

        subs_g = metrics.get("subscribersGained")
        if subs_g is not None:
            try:
                subs_f = float(subs_g)
                subs_ratio = subs_f / max(1.0, views)
                subs_scaled = clamp(subs_ratio / 0.01, 0.0, 1.0)
                terms.append(subs_scaled)
                weights.append(0.05)
            except Exception:
                pass

        age_h = metrics.get("ageHours")
        if age_h is not None:
            try:
                age_f = max(1.0, float(age_h))
                vph = views / age_f
                # log scale: 200 views/hour ~= strong early performance
                views_term = clamp(math.log1p(vph) / math.log1p(200.0), 0.0, 1.0)
                terms.append(views_term)
                weights.append(0.08)
            except Exception:
                pass

        tw = sum(weights)
        if tw <= 0:
            return None

        score = sum(t * w for t, w in zip(terms, weights)) / tw
        return float(clamp(score, 0.0, 1.0))
    except Exception:
        return None
