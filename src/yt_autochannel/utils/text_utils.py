from __future__ import annotations

import hashlib
import re
import textwrap
from typing import List


BAD_FRAGMENT = "d}"


def sanitize_text(s: str) -> str:
    s = s.replace(BAD_FRAGMENT, "")
    s = s.replace("\u200b", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_for_dupe(s: str) -> str:
    s = sanitize_text(s)
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def stable_hash(s: str) -> str:
    b = s.encode("utf-8")
    return hashlib.sha256(b).hexdigest()


def wrap_lines(s: str, width: int) -> str:
    s = sanitize_text(s)
    lines: List[str] = []
    for para in s.split("\n"):
        para = para.strip()
        if not para:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(para, width=width, break_long_words=False, replace_whitespace=False))
    return "\n".join(lines)
