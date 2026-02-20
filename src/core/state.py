import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.config import CONFIG


class StateStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CONFIG.data_dir / "state.json"
        if not self.path.exists():
            self._write(
                {
                    "initialized": False,
                    "question_history": [],
                    "cta_history": [],
                    "title_history": [],
                    "template_index": 0,
                    "uploads": [],
                    "last_short_at": None,
                    "last_long_at": None,
                }
            )

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text())

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(payload, indent=2))

    def get(self) -> dict[str, Any]:
        return self._read()

    def update(self, mutate) -> dict[str, Any]:
        state = self._read()
        mutate(state)
        self._write(state)
        return state

    def is_duplicate_question(self, question: str, days: int = 15) -> bool:
        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        for item in self._read().get("question_history", []):
            when = datetime.fromisoformat(item["created_at"])
            if when > threshold and item["question"].strip().lower() == question.strip().lower():
                return True
        return False
