from __future__ import annotations

import hashlib
import os
import random
import re
import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_date_yyyymmdd(dt: datetime | None = None) -> str:
    dt = dt or utc_now()
    return dt.strftime("%Y%m%d")


def utc_date_iso(dt: datetime | None = None) -> str:
    dt = dt or utc_now()
    return dt.strftime("%Y-%m-%d")


def parse_yyyymmdd(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def normalize_text(s: str) -> str:
    s = s.strip().lower()
    s = s.replace("&", " and ")
    s = _NORMALIZE_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def wrap_lines(s: str, width: int, max_lines: int) -> str:
    s = s.strip()
    if not s:
        return s
    lines = textwrap.wrap(s, width=width, break_long_words=False, break_on_hyphens=False)
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + ["…"]
    return "\n".join(lines)


def pick_random(items: list[str], seed: int | None = None) -> str:
    if not items:
        raise ValueError("Cannot pick from empty list")
    r = random.Random(seed if seed is not None else random.randint(1, 10**9))
    return r.choice(items)


def env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v is not None else default


def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip().lower()
    return v in ("1", "true", "yes", "y", "on")


def env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v.strip())
    except Exception:
        return default


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_sleep_s: float = 0.8
    max_sleep_s: float = 10.0


def backoff_sleep_s(attempt: int, policy: RetryPolicy, jitter: float = 0.35) -> float:
    import math

    raw = policy.base_sleep_s * (2 ** (attempt - 1))
    raw = min(raw, policy.max_sleep_s)
    j = raw * jitter
    return max(0.0, raw + random.uniform(-j, j))


def clamp_list_str(items: Iterable[str], max_items: int, max_total_chars: int) -> list[str]:
    out: list[str] = []
    total = 0
    for it in items:
        it = (it or "").strip()
        if not it:
            continue
        if len(out) >= max_items:
            break
        if total + len(it) > max_total_chars:
            break
        out.append(it)
        total += len(it)
    return out


def safe_filename(s: str) -> str:
    s = normalize_text(s)[:80]
    s = s.replace(" ", "-")
    s = re.sub(r"[^a-z0-9\-]+", "", s)
    s = s.strip("-")
    return s or "item"
