from __future__ import annotations

import re
import textwrap
from typing import Iterable


def normalize_text(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^a-z0-9 \-\?\!\.,:'\"]+", "", s)
    return s.strip()


def sha256_hex(s: str) -> str:
    import hashlib

    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()


def wrap_for_display(text: str, max_chars: int = 28, max_lines: int = 4) -> str:
    lines = textwrap.wrap(text, width=max_chars, break_long_words=False, break_on_hyphens=False)
    if not lines:
        return text.strip()
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + ["…"]
    return "\n".join(lines)


def clamp_list(items: Iterable[str], max_total_chars: int) -> list[str]:
    out: list[str] = []
    total = 0
    for it in items:
        it2 = (it or "").strip()
        if not it2:
            continue
        if it2 in out:
            continue
        add = len(it2) + (2 if out else 0)
        if total + add > max_total_chars:
            break
        out.append(it2)
        total += add
    return out
