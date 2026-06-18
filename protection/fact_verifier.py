"""
protection/fact_verifier.py
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
import structlog
from cascade.llm.llm_cascade import get_llm

logger = structlog.get_logger(__name__)

_MIN_CONFIDENCE = 65
_HIGH_CONFIDENCE_SKIP = 85
_MIN_SOURCES_FOR_SKIP = 2


@dataclass
class FactVerificationResult:
    fact_text:   str
    is_verified: bool
    confidence:  int
    concern:     Optional[str] = None


class FactVerifier:

    def __init__(self) -> None:
        self._llm = get_llm()

    # ── Public API ────────────────────────────────────────────────────────────

    def verify_facts(self, facts: List[Dict], topic_name: str) -> List[Dict]:
        """
        Return a new list of fact dicts annotated with:
            is_verified (bool), confidence_score (int, possibly adjusted),
            verification_concern (str, optional)
        """
        verified: List[Dict] = []
        for f in facts:
            result = self._verify_one(f, topic_name)
            f2 = dict(f)
            f2["is_verified"]    = result.is_verified
            f2["confidence_score"] = result.confidence
            if result.concern:
                f2["verification_concern"] = result.concern
            verified.append(f2)

        n_ok = sum(1 for f in verified if f["is_verified"])
        logger.info("facts_verified", topic=topic_name, total=len(verified), passed=n_ok)
        return verified

    def filter_usable(self, facts: List[Dict]) -> List[Dict]:
        """Return only facts that passed verification with sufficient confidence."""
        return [
            f for f in facts
            if f.get("is_verified") and int(f.get("confidence_score", 0)) >= _MIN_CONFIDENCE
        ]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _verify_one(self, fact: Dict, topic_name: str) -> FactVerificationResult:
        fact_text     = fact.get("fact_text", "")
        existing_conf = int(fact.get("confidence_score", 0))
        source_count  = int(fact.get("source_count", 0))

        # Already high-confidence multi-source facts skip the LLM call
        if existing_conf >= _HIGH_CONFIDENCE_SKIP and source_count >= _MIN_SOURCES_FOR_SKIP:
            return FactVerificationResult(fact_text, True, existing_conf)

        source_names = fact.get("source_names")
        if not source_names:
            single = fact.get("source_name")
            source_names = [single] if single else []

        try:
            check = self._llm.verify_fact_consistency(fact_text, topic_name, source_names)
            plausible  = bool(check.get("plausible", True))
            confidence = int(check.get("confidence", existing_conf or 60))
            concern    = check.get("concern")
            is_verified = plausible and confidence >= _MIN_CONFIDENCE
            return FactVerificationResult(fact_text, is_verified, confidence, concern)
        except Exception as exc:
            logger.debug("fact_verify_llm_skip", error=str(exc)[:80])
            # Neutral fallback — do not block the pipeline on verifier outage
            is_verified = existing_conf >= _MIN_CONFIDENCE
            return FactVerificationResult(fact_text, is_verified, existing_conf or 60)


_instance: Optional[FactVerifier] = None

def get_fact_verifier() -> FactVerifier:
    global _instance
    if _instance is None:
        _instance = FactVerifier()
    return _instance
