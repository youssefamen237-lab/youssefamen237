from __future__ import annotations

import random
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable, List, Optional, Sequence, Tuple, TypeVar

T = TypeVar("T")


_ws_re = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.strip().lower()
    s = _ws_re.sub(" ", s)
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)
    return s


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def clamp_text(s: str, max_chars: int) -> str:
    s = s.strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1].rstrip() + "…"


def choose_weighted(items: Sequence[T], weights: Sequence[float]) -> T:
    if len(items) != len(weights) or not items:
        raise ValueError("Invalid items/weights")
    total = float(sum(max(0.0, w) for w in weights))
    if total <= 0:
        return random.choice(list(items))
    r = random.random() * total
    upto = 0.0
    for item, w in zip(items, weights):
        w = max(0.0, float(w))
        upto += w
        if upto >= r:
            return item
    return items[-1]


def shuffle_copy(items: Sequence[T]) -> List[T]:
    out = list(items)
    random.shuffle(out)
    return out


def ffmpeg_escape_text(s: str) -> str:
    # Escape for ffmpeg drawtext.
    # Based on ffmpeg drawtext rules: ':' and '\\' and "'" need escaping.
    s = s.replace("\\", "\\\\")
    s = s.replace(":", "\\:")
    s = s.replace("'", "\\'")
    s = s.replace("%", "\\%")
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "")
    return s
