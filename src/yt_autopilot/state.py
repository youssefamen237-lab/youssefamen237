\
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .settings import DATA_DIR


STATE_PATH = DATA_DIR / "state.json"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class ChannelState:
    bootstrapped: bool
    bootstrapped_at: Optional[str]
    schedule: List[Dict[str, Any]]
    last_schedule_refresh_utc: Optional[str]
    daily_counters: Dict[str, Any]
    weekly_counters: Dict[str, Any]
    last_run_utc: Optional[str]

    @staticmethod
    def load(path: Path = STATE_PATH) -> "ChannelState":
        if not path.exists():
            return ChannelState(
                bootstrapped=False,
                bootstrapped_at=None,
                schedule=[],
                last_schedule_refresh_utc=None,
                daily_counters={},
                weekly_counters={},
                last_run_utc=None,
            )
        doc = json.loads(path.read_text(encoding="utf-8"))
        return ChannelState(
            bootstrapped=bool(doc.get("bootstrapped", False)),
            bootstrapped_at=doc.get("bootstrapped_at"),
            schedule=list(doc.get("schedule") or []),
            last_schedule_refresh_utc=doc.get("last_schedule_refresh_utc"),
            daily_counters=dict(doc.get("daily_counters") or {}),
            weekly_counters=dict(doc.get("weekly_counters") or {}),
            last_run_utc=doc.get("last_run_utc"),
        )

    def save(self, path: Path = STATE_PATH) -> None:
        atomic_write_json(
            path,
            {
                "bootstrapped": self.bootstrapped,
                "bootstrapped_at": self.bootstrapped_at,
                "schedule": self.schedule,
                "last_schedule_refresh_utc": self.last_schedule_refresh_utc,
                "daily_counters": self.daily_counters,
                "weekly_counters": self.weekly_counters,
                "last_run_utc": self.last_run_utc,
            },
        )

    def _today_key(self) -> str:
        return utc_now().date().isoformat()

    def _week_key(self) -> str:
        d = utc_now().date()
        iso = d.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    def get_daily_counter(self, name: str) -> int:
        day = self._today_key()
        return int(((self.daily_counters.get(day) or {}).get(name)) or 0)

    def inc_daily_counter(self, name: str, amount: int = 1) -> None:
        day = self._today_key()
        self.daily_counters.setdefault(day, {})
        self.daily_counters[day][name] = int(self.daily_counters[day].get(name, 0)) + amount

    def get_weekly_counter(self, name: str) -> int:
        wk = self._week_key()
        return int(((self.weekly_counters.get(wk) or {}).get(name)) or 0)

    def inc_weekly_counter(self, name: str, amount: int = 1) -> None:
        wk = self._week_key()
        self.weekly_counters.setdefault(wk, {})
        self.weekly_counters[wk][name] = int(self.weekly_counters[wk].get(name, 0)) + amount

    def prune_old_counters(self, keep_days: int = 45, keep_weeks: int = 12) -> None:
        try:
            # daily
            all_days = sorted(self.daily_counters.keys())
            if len(all_days) > keep_days:
                for k in all_days[: len(all_days) - keep_days]:
                    self.daily_counters.pop(k, None)

            # weekly
            all_w = sorted(self.weekly_counters.keys())
            if len(all_w) > keep_weeks:
                for k in all_w[: len(all_w) - keep_weeks]:
                    self.weekly_counters.pop(k, None)
        except Exception:
            pass
