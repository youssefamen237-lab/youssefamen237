from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


UTC = timezone.utc


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def utc_date_str(dt: datetime) -> str:
    return dt.astimezone(UTC).date().isoformat()


def rfc3339(dt: datetime) -> str:
    d = dt.astimezone(UTC).replace(microsecond=0)
    return d.isoformat().replace("+00:00", "Z")


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()


def normalize_text(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    return s.strip()


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def safe_slug(s: str, max_len: int = 60) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if not s:
        s = "item"
    return s[:max_len].strip("-") or "item"


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def json_loads(s: str | None) -> Any:
    if not s:
        return None
    return json.loads(s)


def save_json(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_cmd(cmd: list[str], timeout: int | None = None, retries: int = 0, retry_sleep: float = 1.0) -> str:
    last_err: Exception | None = None
    last_stderr: str = ""
    for attempt in range(retries + 1):
        try:
            p = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=True,
                text=True,
            )
            return p.stdout
        except subprocess.CalledProcessError as e:
            last_err = e
            if e.stderr:
                last_stderr = e.stderr
            if attempt >= retries:
                break
            time.sleep(retry_sleep * (1.5 ** attempt))
        except Exception as e:
            last_err = e
            if attempt >= retries:
                break
            time.sleep(retry_sleep * (1.5 ** attempt))

    msg = f"Command failed: {shlex.join(cmd)}"
    if last_stderr:
        tail = last_stderr[-4000:]
        msg += f"\n--- STDERR (last 4000 chars) ---\n{tail}\n"
    raise RuntimeError(msg) from last_err


def ffprobe_duration_seconds(path: Path) -> float:
    out = run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        timeout=60,
        retries=1,
        retry_sleep=1.0,
    ).strip()
    try:
        return float(out)
    except Exception:
        return 0.0


def weighted_choice(rng: random.Random, items: list[str], weights: list[float]) -> str:
    if len(items) != len(weights) or not items:
        return rng.choice(items) if items else ""
    total = sum(max(0.0, float(w)) for w in weights)
    if total <= 0:
        return rng.choice(items)
    r = rng.random() * total
    acc = 0.0
    for item, w in zip(items, weights):
        acc += max(0.0, float(w))
        if r <= acc:
            return item
    return items[-1]


def env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    s = v.strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def env_int(name: str, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    v = os.getenv(name)
    if v is None or not v.strip():
        x = default
    else:
        try:
            x = int(v.strip())
        except Exception:
            x = default
    if min_value is not None:
        x = max(min_value, x)
    if max_value is not None:
        x = min(max_value, x)
    return x


def env_float(name: str, default: float, min_value: float | None = None, max_value: float | None = None) -> float:
    v = os.getenv(name)
    if v is None or not v.strip():
        x = default
    else:
        try:
            x = float(v.strip())
        except Exception:
            x = default
    if min_value is not None:
        x = max(min_value, x)
    if max_value is not None:
        x = min(max_value, x)
    return x


@dataclass(frozen=True)
class TimeWindow:
    start_h: int
    start_m: int
    end_h: int
    end_m: int

    @staticmethod
    def parse_one(s: str) -> "TimeWindow":
        s = s.strip()
        a, b = s.split("-", 1)
        sh, sm = [int(x) for x in a.split(":")]
        eh, em = [int(x) for x in b.split(":")]
        return TimeWindow(sh, sm, eh, em)

    @staticmethod
    def parse_csv(s: str) -> list["TimeWindow"]:
        out: list[TimeWindow] = []
        for part in (s or "").split(","):
            p = part.strip()
            if not p:
                continue
            out.append(TimeWindow.parse_one(p))
        if not out:
            out.append(TimeWindow(14, 30, 17, 30))
        return out

    def pick_datetime(self, day: datetime, rng: random.Random) -> datetime:
        d = day.astimezone(UTC)
        start = d.replace(hour=self.start_h, minute=self.start_m, second=0, microsecond=0)
        end = d.replace(hour=self.end_h, minute=self.end_m, second=0, microsecond=0)

        if end <= start:
            end = end + timedelta(days=1)

        span = int((end - start).total_seconds())
        if span <= 0:
            return start
        offset = rng.randint(0, span - 1)
        return start + timedelta(seconds=offset)
