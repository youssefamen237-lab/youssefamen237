from __future__ import annotations

import re


_BANNED_PATTERNS = [
    r"\b(?:sex|porn|nude|naked|xxx)\b",
    r"\b(?:hitler|nazi|kkk)\b",
    r"\b(?:terror(?:ism|ist)?|isis|al\s*qaeda)\b",
    r"\b(?:shooting|bomb|explosive|suicide)\b",
    r"\b(?:racist|slur)\b",
    r"\b(?:genocide|war\s*crime)\b",
    r"\b(?:election|president|prime\s*minister)\b",
    r"\b(?:religion|allah|jesus|bible|quran)\b",
    r"\b(?:covid|vaccine|cancer|diabetes)\b",
]


_BANNED = [re.compile(pat, re.IGNORECASE) for pat in _BANNED_PATTERNS]


def is_safe_text(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if len(t) < 2:
        return False
    for rx in _BANNED:
        if rx.search(t):
            return False
    return True


def sanitize_title(s: str, max_len: int = 95) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = s[:max_len].strip()
    return s


def sanitize_description(s: str, max_len: int = 4900) -> str:
    s = (s or "").strip()
    s = re.sub(r"\r\n", "\n", s)
    s = s[:max_len].strip()
    return s


def sanitize_tags(tags: list[str], max_tags: int = 15) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in tags:
        x = (t or "").strip()
        if not x:
            continue
        key = x.lower()
        if key in seen:
            continue
        if len(x) > 30:
            x = x[:30]
        seen.add(key)
        out.append(x)
        if len(out) >= max_tags:
            break
    return out


def sanitize_hashtags(tags: list[str], max_tags: int = 5) -> list[str]:
    out: list[str] = []
    for t in tags:
        x = (t or "").strip()
        if not x:
            continue
        if not x.startswith("#"):
            x = "#" + x
        x = re.sub(r"[^\w#]", "", x)
        if len(x) < 2:
            continue
        out.append(x[:30])
        if len(out) >= max_tags:
            break
    return out
