"""
protection/policy_guard.py
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)

_ALLOWED_CATEGORIES = frozenset({"ocean", "animals", "space", "nature", "birds", "insects"})

_BANNED_TOPIC_KEYWORDS: list = [
    "politic", "election", "president", "war", "religion", "religious",
    "god", "islam", "muslim", "christ", "jewish", "judaism", "hindu",
    "celebrity", "kardashian", "crime", "murder", "terrorist", "terrorism",
    "weapon", "firearm", " gun ", "suicide", "abortion", "vaccine",
]

_MEDICAL_CLAIM_PATTERNS: list = [
    r"\bcures?\b",
    r"\btreats?\b.*\b(disease|cancer|illness|condition)\b",
    r"\bheals?\b.*\b(cancer|disease|wound|illness)\b",
    r"\bprevents?\b.*\b(covid|cancer|disease|virus)\b",
    r"\bvaccine\b",
    r"\bcan be used to (treat|cure|heal)\b",
]

_VIOLENCE_PATTERNS: list = [
    r"\bkills?\b\s+(a |an |the )?(human|person|man|woman|child|people)\b",
    r"\bmurders?\b",
    r"\battacks?\b\s+(a |an |the )?(human|person|man|woman|child)\b",
    r"\bhow to (kill|harm|hurt)\b",
]


@dataclass
class PolicyCheckResult:
    allowed: bool
    reason:  Optional[str] = None


class PolicyGuard:

    # ── Topic-level checks ────────────────────────────────────────────────────

    def check_topic(self, topic_name: str, category: str) -> PolicyCheckResult:
        text = f" {topic_name.lower()} "
        for kw in _BANNED_TOPIC_KEYWORDS:
            if kw in text:
                return PolicyCheckResult(False, f"banned_keyword_in_topic:{kw.strip()}")

        if category not in _ALLOWED_CATEGORIES:
            return PolicyCheckResult(False, f"category_not_in_constitution:{category}")

        return PolicyCheckResult(True)

    # ── Script-level checks ───────────────────────────────────────────────────

    def check_script_text(self, full_text: str) -> PolicyCheckResult:
        text = f" {full_text.lower()} "

        for kw in _BANNED_TOPIC_KEYWORDS:
            if kw in text:
                return PolicyCheckResult(False, f"banned_keyword_in_script:{kw.strip()}")

        for pattern in _MEDICAL_CLAIM_PATTERNS:
            if re.search(pattern, text):
                return PolicyCheckResult(False, f"medical_claim_detected:{pattern}")

        for pattern in _VIOLENCE_PATTERNS:
            if re.search(pattern, text):
                return PolicyCheckResult(False, f"violence_against_humans:{pattern}")

        return PolicyCheckResult(True)

    # ── Fact-level checks ─────────────────────────────────────────────────────

    def check_fact(self, fact_text: str) -> PolicyCheckResult:
        text = f" {fact_text.lower()} "
        for pattern in _MEDICAL_CLAIM_PATTERNS:
            if re.search(pattern, text):
                return PolicyCheckResult(False, f"medical_claim_in_fact:{pattern}")
        return PolicyCheckResult(True)

    def filter_facts(self, facts: list) -> list:
        """Remove any facts that fail policy checks. Never raises."""
        clean = []
        for f in facts:
            text = f.get("fact_text", "")
            if not text:
                continue
            result = self.check_fact(text)
            if result.allowed:
                clean.append(f)
            else:
                logger.info("fact_blocked_by_policy", reason=result.reason, fact=text[:80])
        return clean

    # ── Combined check ────────────────────────────────────────────────────────

    def check_all(self, topic_name: str, category: str, full_text: str) -> PolicyCheckResult:
        r1 = self.check_topic(topic_name, category)
        if not r1.allowed:
            logger.warning("policy_rejected_topic", topic=topic_name, reason=r1.reason)
            return r1

        r2 = self.check_script_text(full_text)
        if not r2.allowed:
            logger.warning("policy_rejected_script", topic=topic_name, reason=r2.reason)
            return r2

        return PolicyCheckResult(True)


_instance: Optional[PolicyGuard] = None

def get_policy_guard() -> PolicyGuard:
    global _instance
    if _instance is None:
        _instance = PolicyGuard()
    return _instance
