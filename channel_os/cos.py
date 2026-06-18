"""
channel_os/cos.py

Channel Operating System — the single point of authority for strategy
changes.  Runs weekly: gathers proposals from GrowthManager (already
filtered through PortfolioManager's diversity guardrails), applies them via
db.update_rule() — which itself silently rejects changes to locked
(constitutional) rules — and records a full decision trail as a
channel_dna learning_memory entry.

Run via: python -m channel_os.cos
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, List, Optional
import structlog

from storage.supabase_client import get_db
from channel_os.growth_manager import get_growth_manager

logger = structlog.get_logger(__name__)

_ADJUSTABLE_RULES = ("category_allocation", "voice_split")


class ChannelOS:

    def __init__(self) -> None:
        self._db     = get_db()
        self._growth = get_growth_manager()

    # ── Public API ────────────────────────────────────────────────────────────

    def run_weekly_review(self) -> Dict:
        changes: List[Dict] = []

        cat_proposal = self._growth.propose_category_allocation()
        if cat_proposal:
            changes.append(self._apply(
                rule_name="category_allocation",
                current=cat_proposal["current"],
                proposed=cat_proposal["proposed"],
                reason=cat_proposal["reason"],
            ))

        voice_proposal = self._growth.propose_voice_split()
        if voice_proposal:
            changes.append(self._apply(
                rule_name="voice_split",
                current=voice_proposal["current"],
                proposed=voice_proposal["proposed"],
                reason=voice_proposal["reason"],
            ))

        decision = {
            "run_at":  datetime.now(timezone.utc).isoformat(),
            "changes": changes,
            "summary": (
                f"{sum(1 for c in changes if c['applied'])} rule(s) adjusted."
                if changes else
                "No changes — insufficient data, locked rules, or already optimal."
            ),
        }

        self._record_decision(decision)
        logger.info(
            "cos_weekly_review_complete",
            proposals=len(changes),
            applied=sum(1 for c in changes if c["applied"]),
        )
        return decision

    # ── Internal ──────────────────────────────────────────────────────────────

    def _apply(self, rule_name: str, current, proposed, reason: str) -> Dict:
        applied = self._db.update_rule(
            rule_name=rule_name, new_value=proposed,
            reason=reason, updated_by="cos.growth_manager",
        )
        return {
            "rule":    rule_name,
            "applied": applied,
            "from":    current,
            "to":      proposed,
            "reason":  reason,
        }

    def _record_decision(self, decision: Dict) -> None:
        try:
            self._db.upsert_memory(
                memory_type="channel_dna", memory_key="latest_cos_decision",
                memory_value=decision, confidence=100.0, data_points=1,
            )
        except Exception as exc:
            logger.warning("cos_decision_log_failed", error=str(exc)[:120])


_instance: Optional[ChannelOS] = None

def get_cos() -> ChannelOS:
    global _instance
    if _instance is None:
        _instance = ChannelOS()
    return _instance


if __name__ == "__main__":
    import json
    result = get_cos().run_weekly_review()
    print(json.dumps(result, indent=2, default=str))
