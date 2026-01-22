\
from __future__ import annotations

import re
from typing import List


def normalize_key(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^a-z0-9:_\- ]+", "", s)
    return s


def wrap_text(text: str, max_chars: int = 28) -> str:
    """
    Naive line wrapper by character count (works well enough for Shorts captions).
    Returns text with '\\n' line breaks.
    """
    words = text.split()
    lines: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for w in words:
        add = len(w) + (1 if cur else 0)
        if cur_len + add > max_chars:
            lines.append(" ".join(cur))
            cur = [w]
            cur_len = len(w)
        else:
            cur.append(w)
            cur_len += add
    if cur:
        lines.append(" ".join(cur))
    return "\n".join(lines)


def ffmpeg_escape(text: str) -> str:
    """
    Escape text for ffmpeg drawtext.
    - Escape ':' and '\\' and apostrophes.
    """
    # ffmpeg drawtext uses ':' as separator, so escape it
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\\'")
    text = text.replace("\n", "\\n")
    return text
