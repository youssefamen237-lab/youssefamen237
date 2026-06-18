"""
reporting/daily_dashboard.py

Builds the "Channel War Room" markdown report — a single-glance snapshot
of buffer health, recent performance, category breakdown, monetization
progress, and the most recent Channel Operating System decision.

Run via: python -m reporting.daily_dashboard [output_path]
(default output_path: STATUS.md)
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, List, Optional
import structlog

from storage.supabase_client import get_db

logger = structlog.get_logger(__name__)


class DailyDashboard:

    def __init__(self) -> None:
        self._db = get_db()

    # ── Public API ────────────────────────────────────────────────────────────

    def build(self) -> str:
        war_room      = self._safe(self._db.get_war_room_snapshot, {})
        categories    = self._safe(self._db.get_category_performance_summary, [])
        monetization  = self._safe(lambda: self._db.get_memory("channel_dna", "monetization_status"), None)
        cos_decision  = self._safe(lambda: self._db.get_memory("channel_dna", "latest_cos_decision"), None)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        lines: List[str] = ["# Channel War Room", "", f"_Last updated: {now}_", ""]
        lines += self._buffer_section(war_room)
        lines += self._performance_section(war_room)
        lines += self._category_section(categories)
        lines += self._monetization_section(monetization)
        lines += self._cos_section(cos_decision)

        return "\n".join(lines) + "\n"

    def write(self, path: str = "STATUS.md") -> str:
        content = self.build()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return content

    # ── Sections ──────────────────────────────────────────────────────────────

    def _buffer_section(self, w: Dict) -> List[str]:
        lines = ["## Content Buffer & Queue Health", ""]
        if not w:
            lines += ["_No data available._", ""]
            return lines
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        lines.append(f"| Shorts ready | {w.get('shorts_ready', 0)} |")
        lines.append(f"| Long-form ready | {w.get('longs_ready', 0)} |")
        lines.append(f"| In production | {w.get('in_production', 0)} |")
        lines.append(f"| Failed (24h) | {w.get('failed_last_24h', 0)} |")
        lines.append(f"| Rejected (24h) | {w.get('rejected_last_24h', 0)} |")
        lines.append(f"| Topics available | {w.get('topics_available', 0)} |")
        lines.append(f"| Facts ready | {w.get('facts_ready', 0)} |")
        lines.append("")
        return lines

    def _performance_section(self, w: Dict) -> List[str]:
        lines = ["## Performance (Last 7 / 30 Days)", ""]
        if not w:
            lines += ["_No data available._", ""]
            return lines
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        lines.append(f"| Published today | {w.get('published_today', 0)} |")
        lines.append(f"| Published (7d) | {w.get('published_last_7d', 0)} |")
        lines.append(f"| Total published (lifetime) | {w.get('total_published', 0)} |")
        lines.append(f"| Views (7d) | {w.get('views_last_7d', 0)} |")
        lines.append(f"| Avg retention (7d) | {w.get('avg_retention_7d', 0)}% |")
        lines.append(f"| Avg CTR (7d) | {w.get('avg_ctr_7d', 0)}% |")
        lines.append(f"| Revenue (30d) | ${w.get('revenue_last_30d', 0)} |")
        lines.append(f"| Best category (30d) | {w.get('best_category') or '—'} |")
        lines.append(f"| Worst category (30d) | {w.get('worst_category') or '—'} |")
        lines.append("")
        return lines

    def _category_section(self, categories: List[Dict]) -> List[str]:
        lines = ["## Category Performance (Last 30 Days)", ""]
        if not categories:
            lines += ["_No data available yet._", ""]
            return lines

        lines.append("| Category | Videos | Avg Views | Avg Retention | Avg CTR | Revenue |")
        lines.append("|---|---|---|---|---|---|")
        for c in sorted(categories, key=lambda x: float(x.get("avg_retention") or 0), reverse=True):
            lines.append(
                f"| {c.get('category')} | {c.get('video_count', 0)} | "
                f"{c.get('avg_views', 0)} | {c.get('avg_retention', 0)}% | "
                f"{c.get('avg_ctr', 0)}% | ${c.get('total_revenue', 0)} |"
            )
        lines.append("")
        return lines

    def _monetization_section(self, mem: Optional[Dict]) -> List[str]:
        lines = ["## Monetization Progress", ""]
        if not mem:
            lines += ["_Not yet tracked — run `channel_os.monetization_tracker`._", ""]
            return lines

        v = mem.get("memory_value") or {}
        subs      = v.get("subscriber_count", 0)
        sub_goal  = v.get("subscriber_threshold", 1000)
        sub_left  = v.get("subscribers_remaining", "—")
        hours     = v.get("watch_hours_trailing_365d", 0)
        hour_goal = v.get("watch_hours_threshold", 4000)
        hour_left = v.get("watch_hours_remaining", "—")
        eligible  = v.get("standard_monetization_eligible", False)

        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        lines.append(f"| Subscribers | {subs} / {sub_goal} (need {sub_left} more) |")
        lines.append(f"| Watch hours (365d) | {hours} / {hour_goal} (need {hour_left} more) |")
        lines.append(f"| Eligible for standard monetization | {'✅ Yes' if eligible else '❌ Not yet'} |")
        lines.append("")
        return lines

    def _cos_section(self, mem: Optional[Dict]) -> List[str]:
        lines = ["## Latest Channel Operating System Decision", ""]
        if not mem:
            lines += ["_No COS review has run yet._", ""]
            return lines

        v = mem.get("memory_value") or {}
        lines.append(f"**Run at:** {v.get('run_at', '—')}")
        lines.append("")
        lines.append(f"**Summary:** {v.get('summary', '—')}")
        lines.append("")

        changes = v.get("changes") or []
        if changes:
            lines.append("| Rule | Status | Reason |")
            lines.append("|---|---|---|")
            for c in changes:
                status = "✅ Applied" if c.get("applied") else "🔒 Rejected (locked)"
                lines.append(f"| `{c.get('rule')}` | {status} | {c.get('reason', '')} |")
            lines.append("")
        return lines

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _safe(fn, default):
        try:
            return fn()
        except Exception as exc:
            logger.warning("dashboard_section_failed", error=str(exc)[:120])
            return default


_instance: Optional[DailyDashboard] = None

def get_daily_dashboard() -> DailyDashboard:
    global _instance
    if _instance is None:
        _instance = DailyDashboard()
    return _instance


if __name__ == "__main__":
    import sys
    output_path = sys.argv[1] if len(sys.argv) > 1 else "STATUS.md"
    content = get_daily_dashboard().write(output_path)
    print(content)
