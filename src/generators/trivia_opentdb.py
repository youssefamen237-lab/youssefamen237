from __future__ import annotations

import html
import logging
import random
from typing import Any, Dict, List, Optional, Tuple

import requests

log = logging.getLogger("opentdb")

OPENTDB_ENDPOINT = "https://opentdb.com/api.php"


def _unescape(s: str) -> str:
    return html.unescape(s or "")


def fetch_question(
    *,
    amount: int = 1,
    qtype: str = "multiple",
    difficulty: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    params: Dict[str, Any] = {"amount": amount, "type": qtype}
    if difficulty:
        params["difficulty"] = difficulty
    try:
        r = requests.get(OPENTDB_ENDPOINT, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("opentdb fetch failed: %s", e)
        return None
    if not isinstance(data, dict):
        return None
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return None
    q = results[0]
    if not isinstance(q, dict):
        return None

    question = _unescape(str(q.get("question", "")).strip())
    correct = _unescape(str(q.get("correct_answer", "")).strip())
    incorrect = q.get("incorrect_answers")
    if not isinstance(incorrect, list):
        incorrect = []
    incorrect_list = [_unescape(str(x).strip()) for x in incorrect][:6]
    options = incorrect_list + [correct]
    random.shuffle(options)

    return {
        "source": "opentdb",
        "category": _unescape(str(q.get("category", "")).strip()) or None,
        "difficulty": _unescape(str(q.get("difficulty", "")).strip()) or None,
        "type": _unescape(str(q.get("type", "")).strip()) or None,
        "question": question,
        "answer": correct,
        "options": options,
    }
