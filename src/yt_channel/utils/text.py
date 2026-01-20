from __future__ import annotations

import re
from typing import List


def normalize_for_hash(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def wrap_text(text: str, max_chars: int) -> str:
    """Simple whitespace word-wrap to max_chars per line."""
    text = text.strip()
    if not text:
        return text

    lines: List[str] = []
    for raw_line in text.splitlines():
        words = raw_line.strip().split()
        if not words:
            lines.append("")
            continue

        cur = words[0]
        for w in words[1:]:
            if len(cur) + 1 + len(w) <= max_chars:
                cur += " " + w
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)

    # Remove excessive blank lines
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(lines)


def ffmpeg_escape_text(text: str) -> str:
    """Escape a string for ffmpeg drawtext using single quotes."""
    # drawtext parses ':' as option separators; must escape.
    t = text
    t = t.replace("\\", r"\\")
    t = t.replace(":", r"\:")
    t = t.replace("'", r"\'")
    t = t.replace("%", r"\%")
    t = t.replace("\n", r"\\n")
    t = t.replace("\r", "")
    return t
