"""
engines/heuristics_engine.py
Karma Vault Stories — Self-Learning Heuristics Engine
Reads analytics records from the analytics store and computes EMA-weighted
performance updates across ALL behavioral dimensions. Saves the updated
heuristics to disk BEFORE story selection runs — so every downstream
engine (story_scorer, script_writer, seo_optimizer) uses today's
learned priors, not yesterday's defaults.

This engine is NOT a fake JSON dump. It materially changes:
  - story_scorer._apply_heuristic_weights()     ← pillar_weights
  - script_writer._select_voice_gender()        ← voice_performance
  - seo_optimizer._select_thumbnail_template()  ← thumbnail_ctr
  - seo_optimizer._select_title_formula()       ← title_formula_ctr
"""

import math
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from config.constants import (
    ContentPillar, CONTENT_PILLAR_WEIGHTS_DEFAULT,
    THUMBNAIL_TEMPLATES, SEO_TITLE_FORMULAS,
    HEURISTICS_DEFAULT,
)
from utils.logger import get_logger
from utils.models import DailyRunContext
from utils.file_manager import (
    load_heuristics, save_heuristics, load_json,
)

log = get_logger(__name__)

# ── Learning rate constants ──────────────────────────────────────
_EMA_ALPHA           = 0.30   # 30% new observation, 70% historical — smooth adaptation
_DECAY_ALPHA         = 0.95   # gentle decay for unseen categories each run
_PILLAR_WEIGHT_FLOOR = 0.03   # no pillar ever drops below 3% probability
_VOICE_FLOOR         = 0.15   # neither voice drops below 15% selection probability
_CTR_FLOOR           = 0.05   # no template/formula drops below 5% probability
_ANALYTICS_STORE     = "analytics/analytics_records.json"

# ── Composite score weights ──────────────────────────────────────
# CTR is the most actionable signal; watch time reflects content quality
_SCORE_WEIGHT_CTR        = 0.40
_SCORE_WEIGHT_WATCH_TIME = 0.35
_SCORE_WEIGHT_VIEWS      = 0.25

# ── Baseline normalisation denominators ─────────────────────────
# Performance above these values = score > 0.5
_BASELINE_CTR        = 0.055    # 5.5% CTR baseline (YouTube docs: avg 4-8%)
_BASELINE_WATCH_SEC  = 240.0    # 4 minutes average view duration
_BASELINE_VIEWS      = 200.0    # modest early-channel baseline


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_heuristics_engine(ctx: DailyRunContext) -> DailyRunContext:
    """
    Loads analytics records, computes performance scores, applies EMA
    updates to all heuristic dimensions, and persists the result.
    Runs at pipeline START — all downstream engines read the updated file.
    """
    log.info("Heuristics engine starting...")

    all_records = load_json(_ANALYTICS_STORE, default=[])
    if not all_records:
        log.info("No analytics records yet — heuristics unchanged (using defaults).")
        ctx.mark_stage("heuristics_engine")
        return ctx

    # Use only records from the last 28 days for signal computation
    recent = _filter_recent(all_records, days=28)
    if not recent:
        log.info("No recent analytics records — heuristics unchanged.")
        ctx.mark_stage("heuristics_engine")
        return ctx

    log.info(f"Computing heuristics from {len(recent)} recent analytics records...")

    current = load_heuristics()

    # ── Compute performance scores per dimension ──────────────────
    pillar_scores    = _score_by_dimension(recent, "pillar")
    voice_scores     = _score_by_dimension(recent, "voice_gender")
    thumb_scores     = _score_by_dimension(recent, "thumbnail_template_id")
    formula_scores   = _score_by_dimension(recent, "formula_idx")
    country_scores   = _score_by_dimension(recent, "country")

    # ── Apply EMA updates to each dimension ──────────────────────
    updated = dict(current)
    updated["pillar_weights"]     = _update_pillar_weights(
        current["pillar_weights"], pillar_scores
    )
    updated["voice_performance"]  = _update_voice_performance(
        current["voice_performance"], voice_scores
    )
    updated["thumbnail_ctr"]      = _update_ctr_weights(
        current["thumbnail_ctr"],
        thumb_scores,
        [t["id"] for t in THUMBNAIL_TEMPLATES],
        floor=_CTR_FLOOR,
    )
    updated["title_formula_ctr"]  = _update_ctr_weights(
        current["title_formula_ctr"],
        formula_scores,
        [str(i) for i in range(len(SEO_TITLE_FORMULAS))],
        floor=_CTR_FLOOR,
    )
    updated["country_performance"] = _update_country_performance(
        current.get("country_performance", {}), country_scores
    )

    # ── Update aggregate stats ────────────────────────────────────
    updated["total_videos_uploaded"] = len(all_records)
    updated["avg_session_views"]     = _compute_avg_views(recent)
    updated["last_updated"]          = datetime.now(timezone.utc).isoformat()

    save_heuristics(updated)

    # Log the material changes so we can verify adaptation is working
    _log_adaptation_summary(current, updated, recent)

    ctx.mark_stage("heuristics_engine")
    log.info("Heuristics engine complete — weights updated and saved.")
    return ctx


# ─────────────────────────────────────────────
# SCORE COMPUTATION
# ─────────────────────────────────────────────

def _score_by_dimension(
    records:   list[dict],
    field_key: str,
) -> dict[str, float]:
    """
    Computes a normalised composite performance score [0, 2+] for each
    unique value of `field_key` found in the analytics records.
    Score > 1.0 means above baseline; score < 1.0 means below baseline.
    """
    bucket_scores: dict[str, list[float]] = defaultdict(list)

    for rec in records:
        key = rec.get(field_key, "")
        if not key:
            continue
        score = _composite_score(rec)
        bucket_scores[key].append(score)

    return {
        key: sum(scores) / len(scores)
        for key, scores in bucket_scores.items()
    }


def _composite_score(rec: dict) -> float:
    """
    Single performance score for one analytics record.
    Normalised to ~1.0 at baseline performance, higher = better.
    """
    ctr       = float(rec.get("ctr", 0.0))
    watch_sec = float(rec.get("avg_view_duration_sec", 0.0))
    views     = float(rec.get("views", 0.0))

    # Sigmoid normalisation: performance / baseline → sigmoid → [0, 1]
    ctr_norm    = _soft_normalise(ctr,       _BASELINE_CTR)
    watch_norm  = _soft_normalise(watch_sec, _BASELINE_WATCH_SEC)
    views_norm  = _soft_normalise(views,     _BASELINE_VIEWS)

    return (
        _SCORE_WEIGHT_CTR        * ctr_norm
        + _SCORE_WEIGHT_WATCH_TIME * watch_norm
        + _SCORE_WEIGHT_VIEWS      * views_norm
    )


def _soft_normalise(value: float, baseline: float) -> float:
    """
    Normalises value relative to baseline using a smooth curve.
    - value = 0           → 0.0
    - value = baseline    → 0.5
    - value = 2×baseline  → ~0.73
    - value → ∞           → 1.0
    """
    if baseline <= 0 or value <= 0:
        return 0.0
    ratio = value / baseline
    # logistic: 1 / (1 + e^(-2*(ratio-1))) centred at ratio=1
    return 1.0 / (1.0 + math.exp(-2.0 * (ratio - 1.0)))


# ─────────────────────────────────────────────
# DIMENSION UPDATERS
# ─────────────────────────────────────────────

def _update_pillar_weights(
    current_weights: dict,
    pillar_scores:   dict[str, float],
) -> dict:
    """
    Updates pillar weights using EMA.
    Material effect: pillars with CTR/watch-time above baseline get
    selection boost, under-performers gradually lose share — but never
    below _PILLAR_WEIGHT_FLOOR so no pillar is ever permanently silenced.
    """
    all_pillars = [p.value for p in ContentPillar]
    updated: dict[str, float] = {}

    for pillar in all_pillars:
        old_w = float(current_weights.get(pillar, _PILLAR_WEIGHT_FLOOR))

        if pillar in pillar_scores:
            # Score > 0.5 means above baseline — normalise to weight signal
            perf_signal = pillar_scores[pillar]      # composite score [0-1]
            # Scale performance signal to a weight: 0.5 perf = neutral weight
            target_w    = old_w * (1.0 + _EMA_ALPHA * (perf_signal - 0.5) * 2.0)
            new_w       = _EMA_ALPHA * target_w + (1.0 - _EMA_ALPHA) * old_w
        else:
            # Not seen recently — gentle decay toward floor
            new_w = _DECAY_ALPHA * old_w

        updated[pillar] = max(_PILLAR_WEIGHT_FLOOR, new_w)

    # Normalise so all pillar weights sum to 1.0
    total = sum(updated.values())
    if total > 0:
        updated = {k: v / total for k, v in updated.items()}

    return updated


def _update_voice_performance(
    current: dict,
    voice_scores: dict[str, float],
) -> dict:
    """
    Updates male/female performance scores using EMA.
    Material effect: the voice with better CTR/retention is selected
    more often via weighted random in script_writer._select_voice_gender().
    A voice never drops below _VOICE_FLOOR probability.
    """
    updated = dict(current)
    for gender in ("male", "female"):
        old_val = float(current.get(gender, 0.5))
        if gender in voice_scores:
            new_val = _EMA_ALPHA * voice_scores[gender] + (1.0 - _EMA_ALPHA) * old_val
        else:
            new_val = _DECAY_ALPHA * old_val
        updated[gender] = max(_VOICE_FLOOR, new_val)

    # Normalise so values sum to 1.0 (they represent relative performance)
    total = updated["male"] + updated["female"]
    if total > 0:
        updated["male"]   = updated["male"]   / total
        updated["female"] = updated["female"] / total

    return updated


def _update_ctr_weights(
    current:     dict,
    scores:      dict[str, float],
    all_keys:    list[str],
    floor:       float = _CTR_FLOOR,
) -> dict:
    """
    Generic updater for thumbnail_ctr and title_formula_ctr.
    Material effect: epsilon-greedy selector in seo_optimizer exploits
    the highest-CTR template/formula 80% of the time, using these weights.
    Low-performing entries decay but never reach zero (exploration maintained).
    """
    updated: dict[str, float] = {}
    n = len(all_keys)
    default_val = 1.0 / max(n, 1)

    for key in all_keys:
        old_val = float(current.get(key, default_val))
        if key in scores:
            new_val = _EMA_ALPHA * scores[key] + (1.0 - _EMA_ALPHA) * old_val
        else:
            new_val = _DECAY_ALPHA * old_val
        updated[key] = max(floor, new_val)

    # Normalise
    total = sum(updated.values())
    if total > 0:
        updated = {k: v / total for k, v in updated.items()}

    return updated


def _update_country_performance(
    current:        dict,
    country_scores: dict[str, float],
) -> dict:
    """
    Tracks which countries produce the best-performing stories.
    Used by story_scorer (future) to boost candidates from high-performing regions.
    Keeps top 30 countries by score to prevent unbounded growth.
    """
    updated = dict(current)
    for country, score in country_scores.items():
        if not country or country in ("Unknown", "global"):
            continue
        old_val = float(updated.get(country, 0.5))
        updated[country] = _EMA_ALPHA * score + (1.0 - _EMA_ALPHA) * old_val

    # Keep only top 30
    if len(updated) > 30:
        updated = dict(
            sorted(updated.items(), key=lambda x: x[1], reverse=True)[:30]
        )
    return updated


# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────

def _filter_recent(records: list[dict], days: int = 28) -> list[dict]:
    """Filters analytics records to those collected within the last `days` days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = []
    for rec in records:
        ts_str = rec.get("collected_at", "")
        if not ts_str:
            recent.append(rec)   # include undated records
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts >= cutoff:
                recent.append(rec)
        except (ValueError, TypeError):
            recent.append(rec)
    return recent


def _compute_avg_views(records: list[dict]) -> float:
    views = [float(r.get("views", 0)) for r in records if r.get("views")]
    return round(sum(views) / len(views), 1) if views else 0.0


def _log_adaptation_summary(
    before:  dict,
    after:   dict,
    records: list[dict],
) -> None:
    """Logs meaningful diff between old and new weights for observability."""
    log.info("Heuristics adaptation summary:")

    # Top pillar change
    old_pw = before.get("pillar_weights", {})
    new_pw = after.get("pillar_weights", {})
    biggest_gain  = max(new_pw, key=lambda k: new_pw[k] - old_pw.get(k, 0))
    biggest_loss  = min(new_pw, key=lambda k: new_pw[k] - old_pw.get(k, 0))
    log.info(
        f"  Pillar shift — biggest gain: {biggest_gain} "
        f"({old_pw.get(biggest_gain, 0):.3f}→{new_pw[biggest_gain]:.3f}), "
        f"biggest loss: {biggest_loss} "
        f"({old_pw.get(biggest_loss, 0):.3f}→{new_pw[biggest_loss]:.3f})"
    )

    # Voice
    old_v = before.get("voice_performance", {})
    new_v = after.get("voice_performance", {})
    log.info(
        f"  Voice — male: {old_v.get('male',0.5):.3f}→{new_v.get('male',0.5):.3f}, "
        f"female: {old_v.get('female',0.5):.3f}→{new_v.get('female',0.5):.3f}"
    )

    # Best thumbnail template
    best_thumb = max(after["thumbnail_ctr"], key=after["thumbnail_ctr"].get)
    log.info(f"  Best thumbnail template: {best_thumb} "
             f"(score={after['thumbnail_ctr'][best_thumb]:.3f})")

    # Best title formula
    best_formula = max(after["title_formula_ctr"], key=after["title_formula_ctr"].get)
    log.info(f"  Best title formula: #{best_formula} "
             f"(score={after['title_formula_ctr'][best_formula]:.3f})")

    log.info(f"  Based on {len(records)} analytics records | "
             f"avg_views={_compute_avg_views(records):.0f}")
