\
import re
from typing import Dict, List


def contains_blocklisted_word(text: str, blocklist_words: List[str]) -> bool:
    t = (text or "").lower()
    for w in blocklist_words:
        w = (w or "").strip().lower()
        if not w:
            continue
        if re.search(rf"\b{re.escape(w)}\b", t):
            return True
    return False


def basic_safety_check(question: str, answer: str, config: Dict) -> bool:
    words = (config.get("safety") or {}).get("blocklist_words") or []
    if contains_blocklisted_word(question, words):
        return False
    if contains_blocklisted_word(answer, words):
        return False
    return True
