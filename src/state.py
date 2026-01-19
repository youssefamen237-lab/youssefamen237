from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils.files import atomic_write_json
from .utils.text import normalize_text, sha256_hex
from .utils.time import iso_utc, utc_now


@dataclass
class UsedQuestion:
    q: str
    a: str
    ts: str
    video_id: str | None


class StateStore:
    def __init__(self, path: Path, *, max_used_questions: int = 5000) -> None:
        self.path = path
        self.max_used_questions = max_used_questions
        self.data: dict[str, Any] = {
            "schema_version": 1,
            "used_questions": {},
            "days": {},
            "youtube": {"last_upload_iso": None, "last_video_ids": []},
        }

    def load(self) -> None:
        if not self.path.exists():
            self.save()
            return
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {
                "schema_version": 1,
                "used_questions": {},
                "days": {},
                "youtube": {"last_upload_iso": None, "last_video_ids": []},
            }

        if "used_questions" not in self.data or not isinstance(self.data["used_questions"], dict):
            self.data["used_questions"] = {}
        if "days" not in self.data or not isinstance(self.data["days"], dict):
            self.data["days"] = {}
        if "youtube" not in self.data or not isinstance(self.data["youtube"], dict):
            self.data["youtube"] = {"last_upload_iso": None, "last_video_ids": []}

    def save(self) -> None:
        self._trim_used_questions()
        atomic_write_json(self.path, self.data)

    def _trim_used_questions(self) -> None:
        used = self.data.get("used_questions", {})
        if not isinstance(used, dict):
            self.data["used_questions"] = {}
            return
        if len(used) <= self.max_used_questions:
            return
        items = []
        for k, v in used.items():
            ts = None
            if isinstance(v, dict):
                ts = v.get("ts")
            items.append((ts or "", k))
        items.sort()
        to_remove = len(items) - self.max_used_questions
        for _, k in items[:to_remove]:
            used.pop(k, None)

    def question_hash(self, question: str) -> str:
        return sha256_hex(normalize_text(question))

    def is_used(self, question: str) -> bool:
        h = self.question_hash(question)
        return h in self.data.get("used_questions", {})

    def mark_used(self, question: str, answer: str, *, video_id: str | None = None) -> str:
        h = self.question_hash(question)
        used = self.data.setdefault("used_questions", {})
        used[h] = {
            "q": question,
            "a": answer,
            "ts": iso_utc(utc_now()),
            "video_id": video_id,
        }
        return h

    def set_video_id_for_hash(self, qhash: str, video_id: str) -> None:
        used = self.data.get("used_questions", {})
        if isinstance(used, dict) and qhash in used and isinstance(used[qhash], dict):
            used[qhash]["video_id"] = video_id

    def add_day_entry(self, day_ymd: str, entry: dict[str, Any]) -> None:
        days = self.data.setdefault("days", {})
        if day_ymd not in days or not isinstance(days.get(day_ymd), dict):
            days[day_ymd] = {"shorts": [], "compilation": None}
        if "shorts" in entry:
            for s in entry["shorts"]:
                days[day_ymd].setdefault("shorts", []).append(s)
        if "compilation" in entry:
            days[day_ymd]["compilation"] = entry["compilation"]

    def set_last_upload(self, video_ids: list[str]) -> None:
        yt = self.data.setdefault("youtube", {})
        yt["last_upload_iso"] = iso_utc(utc_now())
        yt["last_video_ids"] = list(video_ids)
