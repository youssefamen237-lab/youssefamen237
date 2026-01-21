from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


def load_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config yaml must be a dict at top-level")
    return data


def env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v


def must_env(name: str) -> str:
    v = env(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def parse_time_window(window: str) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    # "HH:MM-HH:MM"
    window = window.strip()
    if "-" not in window:
        raise ValueError(f"Invalid window: {window}")
    a, b = window.split("-", 1)
    ah, am = a.split(":")
    bh, bm = b.split(":")
    return (int(ah), int(am)), (int(bh), int(bm))


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
