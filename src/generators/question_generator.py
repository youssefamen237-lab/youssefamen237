from __future__ import annotations

import logging
import os
import random
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .types import QuizItem
from . import templates as T
from ..utils.text import normalize_text, similarity, choose_weighted
from ..state import add_history

log = logging.getLogger("question_generator")

TEMPLATE_FACTORIES: Dict[str, Callable[[int, int], Optional[QuizItem]]] = {
    "true_false": lambda mq, ma: T.make_true_false(mq, ma),
    "mcq_3": lambda mq, ma: T.make_mcq_3(mq, ma),
    "fill_blank": lambda mq, ma: T.make_fill_blank(mq, ma),
    "capital_city": lambda mq, ma: T.make_capital_city(mq, ma),
    "quick_math": lambda mq, ma: T.make_quick_math(mq, ma),
    "word_scramble": lambda mq, ma: T.make_word_scramble(mq, ma),
    "emoji_logic": lambda mq, ma: T.make_emoji_logic(mq, ma),
    "spot_difference": lambda mq, ma: T.make_spot_difference(mq, ma),
    "which_one": lambda mq, ma: T.make_which_one(mq, ma),
    "sports_prediction": lambda mq, ma: T.make_sports_prediction(mq, ma),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _template_weight(state: Dict[str, Any], template: str) -> float:
    perf = state.get("performance", {}).get("templates", {})
    rec = perf.get(template)
    if not isinstance(rec, dict):
        return 1.0
    count = int(rec.get("count", 0))
    # Prefer under-used templates slightly.
    return 1.0 / (1.0 + min(20, count) * 0.15)


def _allowed_templates(cfg: Dict[str, Any]) -> List[str]:
    enabled = cfg.get("templates", {}).get("enabled") or []
    optional_requires = cfg.get("templates", {}).get("optional_requires") or {}
    out: List[str] = []
    for t in enabled:
        if t not in TEMPLATE_FACTORIES:
            continue
        req = optional_requires.get(t)
        if isinstance(req, dict):
            # Require listed env vars to be present
            ok = True
            for _, env_name in req.items():
                if not os.getenv(str(env_name), ""):
                    ok = False
                    break
            if not ok:
                continue
        out.append(t)
    if not out:
        out = [k for k in TEMPLATE_FACTORIES.keys() if k != "sports_prediction"]
    return out


def _is_duplicate(state: Dict[str, Any], q: QuizItem, days: int) -> bool:
    hist = state.get("question_history")
    if not isinstance(hist, list) or not hist:
        return False
    qn = normalize_text(q.question)
    for it in hist:
        if not isinstance(it, dict):
            continue
        prev_q = str(it.get("question", ""))
        if not prev_q:
            continue
        if normalize_text(prev_q) == qn:
            return True
        if similarity(prev_q, q.question) >= 0.92:
            return True
        if it.get("qid") == q.qid:
            return True
    return False


def generate_quiz(cfg: Dict[str, Any], state: Dict[str, Any]) -> QuizItem:
    max_q = int(cfg["content"]["short"]["max_question_chars"])
    max_a = int(cfg["content"]["short"]["max_answer_chars"])
    no_repeat_days = int(cfg["safety"]["no_repeat_question_days"])

    templates = _allowed_templates(cfg)
    weights = [_template_weight(state, t) for t in templates]

    for attempt in range(40):
        template = choose_weighted(templates, weights)
        factory = TEMPLATE_FACTORIES.get(template)
        if not factory:
            continue
        item = factory(max_q, max_a)
        if not item:
            continue
        if _is_duplicate(state, item, no_repeat_days):
            continue
        add_history(
            state,
            "question_history",
            {"ts": _now_iso(), "qid": item.qid, "template": item.template, "question": item.question, "answer": item.answer},
            keep_days=no_repeat_days,
        )
        return item

    # Last resort: return something (should be extremely rare)
    fallback = T.make_quick_math(max_q, max_a)
    add_history(
        state,
        "question_history",
        {"ts": _now_iso(), "qid": fallback.qid, "template": fallback.template, "question": fallback.question, "answer": fallback.answer},
        keep_days=no_repeat_days,
    )
    return fallback
