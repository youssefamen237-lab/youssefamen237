"""
engines/topic_selector.py
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import structlog
from storage.supabase_client import get_db
from storage.redis_client import get_redis

logger = structlog.get_logger(__name__)

_DEFAULT_WEIGHTS: Dict[str, int] = {
    "ocean": 30, "animals": 25, "space": 20,
    "nature": 15, "birds": 7,  "insects": 3,
}


@dataclass
class TopicSelection:
    topic_id:           str
    topic_name:         str
    category:           str
    subcategory:        Optional[str]
    visual_keywords:    List[str]         = field(default_factory=list)
    topic_dna:          Dict              = field(default_factory=dict)
    computed_value:     int               = 0
    curiosity_score:    int               = 50
    visual_availability: int              = 50


class TopicSelector:

    def __init__(self) -> None:
        self._db    = get_db()
        self._redis = get_redis()

    def select_next(
        self,
        video_type:         str = "short",
        preferred_category: Optional[str] = None,
        exclude_ids:        Optional[List[str]] = None,
    ) -> TopicSelection:
        exclude_ids = list(exclude_ids or [])

        # Also exclude topics on Redis cooldown (belt-and-suspenders with DB cooldown)
        weights  = self._load_weights()
        attempts = 0
        max_attempts = 6

        while attempts < max_attempts:
            attempts += 1
            category = preferred_category if preferred_category else self._weighted_choice(weights)
            topic    = self._db.get_next_topic(category=category, exclude_ids=exclude_ids)

            if topic:
                # Double-check Redis cooldown
                if self._redis.is_topic_on_cooldown(topic["topic_id"]):
                    exclude_ids.append(topic["topic_id"])
                    continue

                # Set Redis cooldown
                cooldown = int(topic.get("cooldown_days", 30))
                self._redis.set_topic_cooldown(topic["topic_id"], cooldown)

                logger.info(
                    "topic_selected",
                    topic=topic["topic_name"],
                    category=topic["category"],
                    value=topic.get("computed_value", 0),
                )
                return TopicSelection(
                    topic_id=topic["topic_id"],
                    topic_name=topic["topic_name"],
                    category=topic["category"],
                    subcategory=topic.get("subcategory"),
                    visual_keywords=list(topic.get("visual_keywords") or []),
                    topic_dna=dict(topic.get("topic_dna") or {}),
                    computed_value=int(topic.get("computed_value") or 0),
                    curiosity_score=int(topic.get("curiosity_score", 50)),
                    visual_availability=int(topic.get("visual_availability", 50)),
                )

            # No topic in this category — try another
            if preferred_category:
                preferred_category = None   # unlock all categories on next pass
            else:
                # Remove the failed category from weights for this attempt
                weights = {k: v for k, v in weights.items() if k != category}
                if not weights:
                    break

        raise RuntimeError(
            "No eligible topics found in any category. "
            "Seed the topic bank via data/seeds/seed_topics.py."
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_weights(self) -> Dict[str, int]:
        try:
            rule = self._db.get_rule("category_allocation")
            if isinstance(rule, dict) and rule:
                return {str(k): int(v) for k, v in rule.items()}
        except Exception:
            pass
        try:
            cached = self._redis.get_cached_growth_rules()
            if cached and isinstance(cached.get("category_allocation"), dict):
                return {str(k): int(v) for k, v in cached["category_allocation"].items()}
        except Exception:
            pass
        return dict(_DEFAULT_WEIGHTS)

    @staticmethod
    def _weighted_choice(weights: Dict[str, int]) -> str:
        items  = [(k, max(0, v)) for k, v in weights.items()]
        total  = sum(w for _, w in items)
        if total <= 0:
            return items[0][0]
        r = random.uniform(0, total)
        cumulative = 0.0
        for cat, w in items:
            cumulative += w
            if r <= cumulative:
                return cat
        return items[-1][0]


_instance: Optional[TopicSelector] = None

def get_topic_selector() -> TopicSelector:
    global _instance
    if _instance is None:
        _instance = TopicSelector()
    return _instance
