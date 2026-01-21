from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class QuizItem:
    qid: str
    template: str
    question: str
    answer: str
    options: Optional[List[str]]
    category: Optional[str]
    difficulty: Optional[str]
    cta: str
    created_at_iso: str
    extra: Optional[Dict[str, Any]] = None
