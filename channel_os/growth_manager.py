"""
channel_os/growth_manager.py

Reads learning_memory (written by analytics/performance_analyzer.py) and
proposes bounded adjustments to mutable growth_rules.  Every proposal is
passed through PortfolioManager before being returned — proposals that
would violate diversity guardrails come back unchanged (None).

This module only *proposes*; channel_os/cos.py applies proposals via
db.update_rule() and records the decision trail.
"""
from __future__ import annotations
from typing import Dict, Optional
import structlog

from storage.supabase_client import get_db
from channel_os.portfolio_manager import get_portfolio_manager

logger = structlog.get_logger(__name__)

_VALID_CATEGORIES = ("ocean", "animals", "space", "nature", "birds", "insects")
_MIN_CATEGORIES_WITH_DATA = 3
_VOICE_DIFF_THRESHOLD_PCT = 5.0


class GrowthManager:

    def __init__(self) -> None:
        self._db        = get_db()
        self._portfolio = get_portfolio_manager()

    # ── Category allocation ───────────────────────────────────────────────────

    def propose_category_allocation(self) -> Optional[Dict]:
        """
        Returns {"current", "proposed", "reason"} or None if no change is
        warranted (insufficient data, no headroom, or already optimal).
        """
        insights = self._load_category_insights()
        if len(insights) < _MIN_CATEGORIES_WITH_DATA:
            logger.info(
                "growth_manager_insufficient_category_data",
                categories_with_data=len(insights), required=_MIN_CATEGORIES_WITH_DATA,
            )
            return None

        ranked = sorted(insights.items(), key=lambda kv: kv[1]["avg_retention"], reverse=True)
        best_cat, best_data = ranked[0]
        worst_cat, worst_data = ranked[-1]

        if best_cat == worst_cat:
            return None

        current = self._db.get_rule("category_allocation")
        if not isinstance(current, dict) or not current:
            logger.warning("growth_manager_category_allocation_rule_missing")
            return None

        proposed = self._portfolio.clamp_category_allocation(current, best=best_cat, worst=worst_cat)
        if proposed == current:
            return None

        reason = (
            f"{best_cat} retention {best_data['avg_retention']:.2f}% "
            f"> {worst_cat} retention {worst_data['avg_retention']:.2f}% "
            f"(n={best_data['data_points']}/{worst_data['data_points']}) — "
            f"shifted {worst_cat} -> {best_cat}"
        )
        return {"current": current, "proposed": proposed, "reason": reason}

    # ── Voice split ───────────────────────────────────────────────────────────

    def propose_voice_split(self) -> Optional[Dict]:
        comparison = self._db.get_memory("voice_insight", "comparison")
        if not comparison:
            logger.info("growth_manager_no_voice_comparison_yet")
            return None

        value = comparison.get("memory_value") or {}
        leader = value.get("leader")
        diff_pct = float(value.get("female_vs_male_pct", 0) or 0)

        if leader not in ("female", "male"):
            return None
        if abs(diff_pct) < _VOICE_DIFF_THRESHOLD_PCT:
            logger.info(
                "growth_manager_voice_diff_below_threshold",
                diff_pct=diff_pct, threshold=_VOICE_DIFF_THRESHOLD_PCT,
            )
            return None

        current = self._db.get_rule("voice_split")
        if not isinstance(current, dict) or not current:
            logger.warning("growth_manager_voice_split_rule_missing")
            return None

        proposed = self._portfolio.clamp_voice_split(current, leader=leader)
        if proposed == current:
            return None

        reason = (
            f"{leader} voice retention {diff_pct:+.2f}% vs other voice "
            f"(female={value.get('female_avg_retention')}, male={value.get('male_avg_retention')}) "
            f"— shifted split toward {leader}"
        )
        return {"current": current, "proposed": proposed, "reason": reason}

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_category_insights(self) -> Dict[str, Dict]:
        out: Dict[str, Dict] = {}
        for cat in _VALID_CATEGORIES:
            mem = self._db.get_memory("category_insight", cat)
            if not mem:
                continue
            value = mem.get("memory_value") or {}
            if "avg_retention" not in value:
                continue
            out[cat] = {
                "avg_retention": float(value["avg_retention"]),
                "avg_ctr":       float(value.get("avg_ctr", 0)),
                "data_points":   int(mem.get("data_points", 0) or 0),
            }
        return out


_instance: Optional[GrowthManager] = None

def get_growth_manager() -> GrowthManager:
    global _instance
    if _instance is None:
        _instance = GrowthManager()
    return _instance
