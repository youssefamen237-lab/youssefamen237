"""
channel_os/portfolio_manager.py

The Anti-Overfitting Layer.  Growth Manager identifies *which* category or
voice is winning; Portfolio Manager decides *how much* (if any) reallocation
is actually safe — small, bounded, reversible steps only, with hard floors
so no category or voice is ever starved or eliminated regardless of a
short-term performance signal.
"""
from __future__ import annotations
from typing import Dict, Optional
import structlog

logger = structlog.get_logger(__name__)

# Category allocation bounds (percentage points)
_CATEGORY_FLOOR   = 3
_CATEGORY_CEILING = 40
_CATEGORY_STEP    = 2

# Voice split bounds (percentage points)
_VOICE_FLOOR   = 20
_VOICE_CEILING = 80
_VOICE_STEP    = 3


class PortfolioManager:

    # ── Category allocation ───────────────────────────────────────────────────

    def clamp_category_allocation(
        self, current: Dict[str, int], best: str, worst: str, step: int = _CATEGORY_STEP
    ) -> Dict[str, int]:
        """
        Shift up to `step` percentage points from `worst` to `best`.
        A pure transfer — the total always remains unchanged.
        Returns `current` unchanged if no safe shift is possible.
        """
        if best == worst or best not in current or worst not in current:
            return dict(current)

        proposed = dict(current)

        worst_val = int(proposed.get(worst, 0))
        best_val  = int(proposed.get(best, 0))

        room_to_give    = max(0, worst_val - _CATEGORY_FLOOR)
        room_to_receive = max(0, _CATEGORY_CEILING - best_val)
        actual_step = min(step, room_to_give, room_to_receive)

        if actual_step <= 0:
            logger.info(
                "portfolio_category_shift_blocked",
                best=best, worst=worst, worst_val=worst_val, best_val=best_val,
            )
            return dict(current)

        proposed[worst] = worst_val - actual_step
        proposed[best]  = best_val + actual_step

        logger.info(
            "portfolio_category_shift_applied",
            best=best, worst=worst, step=actual_step,
            new_best=proposed[best], new_worst=proposed[worst],
        )
        return proposed

    # ── Voice split ───────────────────────────────────────────────────────────

    def clamp_voice_split(
        self, current: Dict[str, int], leader: str, step: int = _VOICE_STEP
    ) -> Dict[str, int]:
        """
        Shift up to `step` percentage points toward `leader` ("female" or
        "male"), bounded so neither voice ever drops below _VOICE_FLOOR or
        exceeds _VOICE_CEILING.
        """
        if leader not in ("female", "male"):
            return dict(current)

        other = "male" if leader == "female" else "female"
        proposed = dict(current)

        leader_val = int(proposed.get(leader, 50))
        other_val  = int(proposed.get(other, 50))

        room_to_receive = max(0, _VOICE_CEILING - leader_val)
        room_to_give    = max(0, other_val - _VOICE_FLOOR)
        actual_step = min(step, room_to_receive, room_to_give)

        if actual_step <= 0:
            logger.info(
                "portfolio_voice_shift_blocked",
                leader=leader, leader_val=leader_val, other_val=other_val,
            )
            return dict(current)

        proposed[leader] = leader_val + actual_step
        proposed[other]  = other_val - actual_step

        logger.info(
            "portfolio_voice_shift_applied",
            leader=leader, step=actual_step,
            new_leader=proposed[leader], new_other=proposed[other],
        )
        return proposed


_instance: Optional[PortfolioManager] = None

def get_portfolio_manager() -> PortfolioManager:
    global _instance
    if _instance is None:
        _instance = PortfolioManager()
    return _instance
