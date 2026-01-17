from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytz


def utc_now_iso() -> str:
    return datetime.now(tz=pytz.UTC).isoformat()


@dataclass
class ReportItem:
    level: str
    event: str
    data: Dict[str, Any] = field(default_factory=dict)
    ts_utc: str = field(default_factory=utc_now_iso)


@dataclass
class RunReport:
    artifacts_dir: Path
    started_at_utc: str = field(default_factory=utc_now_iso)
    items: List[ReportItem] = field(default_factory=list)

    def add(self, level: str, event: str, data: Dict[str, Any] | None = None) -> None:
        self.items.append(ReportItem(level=level, event=event, data=data or {}))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": utc_now_iso(),
            "items": [
                {"ts_utc": it.ts_utc, "level": it.level, "event": it.event, "data": it.data}
                for it in self.items
            ],
        }

    def write(self) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        json_path = self.artifacts_dir / "run_report.json"
        md_path = self.artifacts_dir / "run_report.md"

        json_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

        lines: List[str] = []
        lines.append("# Run report")
        lines.append("")
        lines.append(f"- Started: {self.started_at_utc}")
        lines.append(f"- Finished: {utc_now_iso()}")
        lines.append("")
        for it in self.items:
            lines.append(f"- [{it.level.upper()}] {it.event}")
            if it.data:
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(it.data, indent=2))
                lines.append("```")
        md_path.write_text("\n".join(lines), encoding="utf-8")
