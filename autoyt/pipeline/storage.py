\
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from autoyt.utils.fs import append_jsonl, read_jsonl
from autoyt.utils.time import utc_now


@dataclass
class HistoryItem:
    created_at: dt.datetime
    dupe_key: str
    kind: str  # short|long
    template_id: str
    meta: Dict[str, Any]


class Storage:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.history_path = repo_root / "data" / "history.jsonl"
        self.video_log_path = repo_root / "data" / "video_log.jsonl"

    def load_history(self, max_lines: int = 5000) -> List[HistoryItem]:
        items: List[HistoryItem] = []
        for obj in read_jsonl(self.history_path, max_lines=max_lines):
            try:
                created = dt.datetime.fromisoformat(obj["created_at"].replace("Z", "+00:00"))
            except Exception:
                continue
            items.append(
                HistoryItem(
                    created_at=created,
                    dupe_key=str(obj.get("dupe_key", "")),
                    kind=str(obj.get("kind", "")),
                    template_id=str(obj.get("template_id", "")),
                    meta=dict(obj.get("meta", {})),
                )
            )
        return items

    def recent_dupe_keys(self, days: int, now: Optional[dt.datetime] = None) -> Set[str]:
        now = now or utc_now()
        cutoff = now - dt.timedelta(days=days)
        keys: Set[str] = set()
        for it in self.load_history():
            if it.created_at >= cutoff and it.dupe_key:
                keys.add(it.dupe_key)
        return keys

    def append_history(
        self,
        dupe_key: str,
        kind: str,
        template_id: str,
        meta: Optional[Dict[str, Any]] = None,
        created_at: Optional[dt.datetime] = None,
    ) -> None:
        created_at = created_at or utc_now()
        append_jsonl(
            self.history_path,
            {
                "created_at": created_at.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "dupe_key": dupe_key,
                "kind": kind,
                "template_id": template_id,
                "meta": meta or {},
            },
        )

    def append_video_log(self, record: Dict[str, Any]) -> None:
        append_jsonl(self.video_log_path, record)

    def load_video_log(self, max_lines: int = 5000) -> List[Dict[str, Any]]:
        return list(read_jsonl(self.video_log_path, max_lines=max_lines))
