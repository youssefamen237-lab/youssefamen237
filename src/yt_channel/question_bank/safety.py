from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


def _load_blocklist(path: Path) -> List[str]:
    terms: List[str] = []
    if not path.exists():
        return terms
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line.lower())
    # Sort longer terms first to catch specific phrases
    terms.sort(key=len, reverse=True)
    return terms


def normalize_text(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


@dataclass(frozen=True)
class SafetyFilter:
    terms: List[str]

    @staticmethod
    def from_file(path: Path) -> "SafetyFilter":
        return SafetyFilter(terms=_load_blocklist(path))

    def is_safe(self, text: str) -> bool:
        t = normalize_text(text)
        for term in self.terms:
            if term and term in t:
                return False
        return True

    def assert_safe(self, parts: Iterable[str]) -> None:
        for p in parts:
            if not self.is_safe(p):
                raise ValueError(f"Blocked content detected: {p}")
