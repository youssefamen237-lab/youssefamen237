from __future__ import annotations

import re
from dataclasses import dataclass


_BANNED_PATTERNS = [
    r"\blyrics?\b",
    r"\bline from (a )?song\b",
    r"\bquote from (a )?(song|movie)\b",
    r"\bwhat song (is|was) this\b",
    r"\bwhich song (is|was) this\b",
    r"\bidentify the song\b",
]

_BANNED_RE = re.compile("|".join(_BANNED_PATTERNS), re.IGNORECASE)

_PROFANITY_HINTS = [
    "nazi",
    "kkk",
    "white power",
    "kill yourself",
    "suicide",
    "rape",
]


@dataclass(frozen=True)
class SafetyResult:
    ok: bool
    reason: str = ""


def validate_text_is_safe(question: str, answer: str) -> SafetyResult:
    q = (question or "").strip()
    a = (answer or "").strip()

    if not q or not a:
        return SafetyResult(False, "empty_question_or_answer")

    if len(q) > 170:
        return SafetyResult(False, "question_too_long")

    if len(a) > 80:
        return SafetyResult(False, "answer_too_long")

    if _BANNED_RE.search(q) or _BANNED_RE.search(a):
        return SafetyResult(False, "copyright_risky_pattern")

    low = (q + " " + a).lower()
    for w in _PROFANITY_HINTS:
        if w in low:
            return SafetyResult(False, "sensitive_or_harmful_content")

    return SafetyResult(True, "")
