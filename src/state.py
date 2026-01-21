from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("state")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_state(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("state json must be dict")
    return data


def save_state(path: str | Path, state: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def prune_history(items: List[Dict[str, Any]], days: int, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or utcnow()
    cutoff = now - timedelta(days=days)
    out: List[Dict[str, Any]] = []
    for it in items:
        ts = it.get("ts")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        if dt >= cutoff:
            out.append(it)
    return out


def add_history(state: Dict[str, Any], key: str, entry: Dict[str, Any], keep_days: int) -> None:
    arr = state.get(key)
    if not isinstance(arr, list):
        arr = []
        state[key] = arr
    arr.append(entry)
    state[key] = prune_history(arr, days=keep_days)


def record_upload(state: Dict[str, Any], upload: Dict[str, Any]) -> None:
    arr = state.get("uploads")
    if not isinstance(arr, list):
        arr = []
        state["uploads"] = arr
    arr.append(upload)


def upsert_perf_counter(state: Dict[str, Any], group: str, key: str, delta_views24: float) -> None:
    perf = state.setdefault("performance", {})
    grp = perf.setdefault(group, {})
    rec = grp.setdefault(key, {"count": 0, "views24_sum": 0.0})
    rec["count"] = int(rec.get("count", 0)) + 1
    rec["views24_sum"] = float(rec.get("views24_sum", 0.0)) + float(delta_views24)
