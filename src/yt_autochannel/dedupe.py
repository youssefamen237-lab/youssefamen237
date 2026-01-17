from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from .db.sqlite_db import DB
from .utils.text_utils import normalize_for_dupe, stable_hash


@dataclass
class DupeResult:
    is_duplicate: bool
    reason: str


def check_duplicate(db: DB, kind: str, text: str, fuzzy_threshold: int, lookback_days: int = 180) -> DupeResult:
    norm = normalize_for_dupe(text)
    h = stable_hash(norm)
    if db.seen_hash(kind, h):
        return DupeResult(True, f"exact_hash:{kind}")

    # near-duplicate against recent sample
    recent = db.recent_norm_texts(kind, days=lookback_days, limit=800)
    for other in recent:
        if not other:
            continue
        score = fuzz.ratio(norm, other)
        if score >= fuzzy_threshold:
            return DupeResult(True, f"fuzzy:{kind}:{score}")
    return DupeResult(False, "ok")


def commit_text(db: DB, kind: str, text: str) -> None:
    norm = normalize_for_dupe(text)
    h = stable_hash(norm)
    db.add_duplicate(kind, norm, h)
