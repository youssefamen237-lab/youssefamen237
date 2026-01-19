from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from yt_auto.utils import normalize_text, parse_yyyymmdd, sha256_hex, utc_now


@dataclass
class UsedQuestion:
    fp: str
    q_norm: str
    question: str
    answer: str
    date_iso: str


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {"version": 1, "bootstrapped": False, "used": [], "publishes": {}}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._save()
            return
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            self._save()
            return
        try:
            self.data = json.loads(raw)
        except Exception:
            self.data = {"version": 1, "bootstrapped": False, "used": [], "publishes": {}}
            self._save()

        if "used" not in self.data or not isinstance(self.data["used"], list):
            self.data["used"] = []
        if "publishes" not in self.data or not isinstance(self.data["publishes"], dict):
            self.data["publishes"] = {}
        if "bootstrapped" not in self.data:
            self.data["bootstrapped"] = False

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def save(self) -> None:
        self._save()

    def is_bootstrapped(self) -> bool:
        return bool(self.data.get("bootstrapped", False))

    def set_bootstrapped(self, v: bool) -> None:
        self.data["bootstrapped"] = bool(v)

    def _date_key(self, yyyymmdd: str) -> str:
        return yyyymmdd

    def was_short_published(self, yyyymmdd: str, slot: int) -> bool:
        dk = self._date_key(yyyymmdd)
        publishes = self.data.get("publishes", {})
        day = publishes.get(dk, {})
        shorts = day.get("shorts", {})
        return str(slot) in shorts

    def record_short(self, yyyymmdd: str, slot: int, video_id: str, artifact_name: str, fp: str) -> None:
        dk = self._date_key(yyyymmdd)
        publishes = self.data.setdefault("publishes", {})
        day = publishes.setdefault(dk, {})
        shorts = day.setdefault("shorts", {})
        shorts[str(slot)] = {"video_id": video_id, "artifact": artifact_name, "fp": fp, "ts": utc_now().isoformat()}

    def was_long_published(self, yyyymmdd: str) -> bool:
        dk = self._date_key(yyyymmdd)
        day = self.data.get("publishes", {}).get(dk, {})
        return "long" in day

    def record_long(self, yyyymmdd: str, video_id: str) -> None:
        dk = self._date_key(yyyymmdd)
        publishes = self.data.setdefault("publishes", {})
        day = publishes.setdefault(dk, {})
        day["long"] = {"video_id": video_id, "ts": utc_now().isoformat()}

    def used_questions_recent(self, days: int) -> list[UsedQuestion]:
        cutoff = (utc_now() - timedelta(days=days)).date()
        out: list[UsedQuestion] = []
        for it in self.data.get("used", []):
            try:
                date_iso = str(it.get("date_iso", "")).strip()
                if not date_iso:
                    continue
                dt = datetime.strptime(date_iso, "%Y-%m-%d").date()
                if dt < cutoff:
                    continue
                out.append(
                    UsedQuestion(
                        fp=str(it.get("fp", "")),
                        q_norm=str(it.get("q_norm", "")),
                        question=str(it.get("question", "")),
                        answer=str(it.get("answer", "")),
                        date_iso=date_iso,
                    )
                )
            except Exception:
                continue
        return out

    def add_used_question(self, question: str, answer: str, date_iso: str) -> str:
        q_norm = normalize_text(question)
        fp = sha256_hex(q_norm)
        self.data.setdefault("used", []).append(
            {"fp": fp, "q_norm": q_norm, "question": question, "answer": answer, "date_iso": date_iso}
        )
        return fp

    def is_duplicate_question(self, question: str, days_window: int, similarity_threshold: float = 0.92) -> bool:
        q_norm = normalize_text(question)
        recent = self.used_questions_recent(days_window)
        for it in recent:
            if it.fp == sha256_hex(q_norm):
                return True
            if it.q_norm and SequenceMatcher(None, q_norm, it.q_norm).ratio() >= similarity_threshold:
                return True
        return False

    def prune_used(self, keep_days: int = 60) -> None:
        cutoff = (utc_now() - timedelta(days=keep_days)).date()
        kept: list[dict[str, Any]] = []
        for it in self.data.get("used", []):
            try:
                date_iso = str(it.get("date_iso", "")).strip()
                if not date_iso:
                    continue
                dt = datetime.strptime(date_iso, "%Y-%m-%d").date()
                if dt >= cutoff:
                    kept.append(it)
            except Exception:
                continue
        self.data["used"] = kept

    def get_short_artifact_names(self, yyyymmdd: str) -> list[str]:
        dk = self._date_key(yyyymmdd)
        day = self.data.get("publishes", {}).get(dk, {})
        shorts = day.get("shorts", {})
        names: list[str] = []
        for slot in ("1", "2", "3", "4"):
            info = shorts.get(slot)
            if info and isinstance(info, dict):
                n = str(info.get("artifact", "")).strip()
                if n:
                    names.append(n)
        return names
