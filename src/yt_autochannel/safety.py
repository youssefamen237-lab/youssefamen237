from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Set

from .utils.text_utils import normalize_for_dupe


def load_blocklist(path: str) -> Set[str]:
    """Load a simple keyword/phrase blocklist (one item per line).

    Blank lines are ignored. Lines starting with '#' are comments.
    """
    if not path or not os.path.exists(path):
        return set()
    words: Set[str] = set()
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            words.add(line.lower())
    return words


@dataclass
class ContentSafety:
    blocked: Set[str]

    @classmethod
    def from_file(cls, path: str) -> 'ContentSafety':
        return cls(blocked=load_blocklist(path))

    def is_safe(self, text: str) -> bool:
        t = normalize_for_dupe(text)
        for w in self.blocked:
            if w and w in t:
                return False
        return True

