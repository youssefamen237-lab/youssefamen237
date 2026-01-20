from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from rapidfuzz import fuzz

from .state.db import StateDB
from .utils.hashing import sha256_hex
from .utils.text import normalize_for_hash


def simhash64(text: str) -> int:
    """Lightweight semantic-ish hash (SimHash) for near-duplicate detection."""
    words = re.findall(r"[a-z0-9]+", normalize_for_hash(text))
    if not words:
        return 0

    v = [0] * 64
    for w in words:
        h = int(sha256_hex(w)[:16], 16)
        for i in range(64):
            bit = (h >> i) & 1
            v[i] += 1 if bit else -1
    out = 0
    for i in range(64):
        if v[i] >= 0:
            out |= (1 << i)
    return out


def hamming(a: int, b: int) -> int:
    x = a ^ b
    return x.bit_count()


@dataclass(frozen=True)
class DedupeResult:
    ok: bool
    reason: str


class DedupeEngine:
    def __init__(self, *, db: StateDB, fuzzy_threshold: int, semantic_enabled: bool = True, semantic_hamming: int = 4) -> None:
        self.db = db
        self.fuzzy_threshold = int(fuzzy_threshold)
        self.semantic_enabled = bool(semantic_enabled)
        self.semantic_hamming = int(semantic_hamming)

    def _exact_key(self, kind: str, text: str) -> str:
        return sha256_hex(kind + ":" + normalize_for_hash(text))

    def check_text(self, *, kind: str, text: str, recent_pool: List[str]) -> DedupeResult:
        key = self._exact_key(kind, text)
        if self.db.has_hash(kind, key):
            return DedupeResult(False, "exact_duplicate")

        norm = normalize_for_hash(text)
        for t in recent_pool:
            r = fuzz.token_sort_ratio(norm, normalize_for_hash(t))
            if r >= self.fuzzy_threshold:
                return DedupeResult(False, f"near_duplicate:{r}")

        if self.semantic_enabled:
            sh = simhash64(text)
            # compare against recent simhashes stored as kind 'simhash:<kind>'
            recent_sh = self.db.recent_hashes(kind=f"simhash:{kind}", limit=300)
            for hexv in recent_sh:
                try:
                    other = int(hexv, 16)
                except Exception:
                    continue
                if hamming(sh, other) <= self.semantic_hamming:
                    return DedupeResult(False, "semantic_duplicate")

        return DedupeResult(True, "ok")

    def register_text(self, *, kind: str, text: str) -> None:
        key = self._exact_key(kind, text)
        self.db.add_hash(kind, key)
        if self.semantic_enabled:
            sh = simhash64(text)
            self.db.add_hash(f"simhash:{kind}", f"{sh:016x}")
