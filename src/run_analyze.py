from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .logger import setup_logging
from .config import load_yaml
from .state import load_state, save_state, upsert_perf_counter
from .utils.time_utils import utcnow
from .youtube.data_api import fetch_videos_snippet_statistics
from .youtube.analytics import query_report

log = logging.getLogger("run_analyze")


def _parse_iso(dt: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except Exception:
        return None


def _ensure_upload_fields(u: Dict[str, Any]) -> None:
    u.setdefault("checked_at", None)
    u.setdefault("views", None)
    u.setdefault("views_24h", None)
    u.setdefault("views_48h", None)
    u.setdefault("perf_counted", False)


def analyze_and_update(cfg: Dict[str, Any], state: Dict[str, Any]) -> None:
    uploads = state.get("uploads")
    if not isinstance(uploads, list) or not uploads:
        log.info("No uploads yet.")
        return

    # Collect video IDs
    vids = [str(u.get("video_id")) for u in uploads if isinstance(u, dict) and u.get("video_id")]
    vids = list(dict.fromkeys([v for v in vids if v]))
    stats = {}
    try:
        stats = fetch_videos_snippet_statistics(vids)
    except Exception as e:
        log.warning("Failed to fetch video statistics: %s", e)
        stats = {}

    now = utcnow()

    for u in uploads:
        if not isinstance(u, dict) or not u.get("video_id"):
            continue
        _ensure_upload_fields(u)
        vid = str(u["video_id"])
        it = stats.get(vid)
        if it:
            st = it.get("statistics") or {}
            try:
                u["views"] = int(st.get("viewCount", 0))
            except Exception:
                u["views"] = u.get("views")
            u["checked_at"] = now.isoformat().replace("+00:00", "Z")

        published = _parse_iso(str(u.get("published_at") or u.get("publish_at") or ""))
        if not published:
            continue
        age = now - published

        # Record 24h and 48h snapshots when first eligible
        if u.get("views") is not None:
            if u.get("views_24h") is None and age >= timedelta(hours=24):
                u["views_24h"] = int(u["views"])
            if u.get("views_48h") is None and age >= timedelta(hours=48):
                u["views_48h"] = int(u["views"])

        # Update performance counters once per upload when views_24h is available
        if not u.get("perf_counted") and u.get("views_24h") is not None:
            views24 = float(u.get("views_24h") or 0)
            template = str(u.get("template") or "unknown")
            voice = str(u.get("voice_id") or "unknown")
            publish_hour = str(u.get("publish_hour_local") if u.get("publish_hour_local") is not None else "")

            if template:
                upsert_perf_counter(state, "templates", template, views24)
            if voice:
                upsert_perf_counter(state, "voices", voice, views24)
            if publish_hour and publish_hour.isdigit():
                upsert_perf_counter(state, "publish_hours", publish_hour, views24)

            u["perf_counted"] = True

    # Optional: pull analytics (if token present) for richer metrics
    channel_id_env = cfg["channel"]["channel_id_env"]
    channel_id = os.getenv(str(channel_id_env), "").strip()
    if channel_id:
        try:
            end_d = date.today()
            start_d = end_d - timedelta(days=28)
            rep = query_report(
                channel_id=channel_id,
                start_date=start_d,
                end_date=end_d,
                metrics="views,estimatedMinutesWatched,averageViewDuration,likes,comments",
                dimensions="video",
                sort="-views",
                max_results=50,
            )
            state.setdefault("analytics_last_28d", rep)
        except Exception as e:
            log.warning("Analytics API not available or failed: %s", e)

    # Write report file
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"daily_report_{now.date().isoformat()}.md"
    report_lines: List[str] = []
    report_lines.append(f"# Daily Report ({now.date().isoformat()})\n")
    report_lines.append(f"- Total tracked uploads: {len(vids)}\n")

    # Top uploads by views_24h (if available) else views
    scored = []
    for u in uploads:
        if not isinstance(u, dict) or not u.get("video_id"):
            continue
        score = u.get("views_24h")
        if score is None:
            score = u.get("views")
        if score is None:
            continue
        scored.append((int(score), u))
    scored.sort(key=lambda x: x[0], reverse=True)

    report_lines.append("## Top Videos\n")
    for score, u in scored[:10]:
        report_lines.append(
            f"- {score} views | {u.get('kind')} | {u.get('template')} | {u.get('voice_id')} | {u.get('title')} | {u.get('video_id')}"
        )
    report_lines.append("\n")

    # Best voices
    report_lines.append("## Voice Performance (avg 24h views)\n")
    voices = state.get("performance", {}).get("voices", {}) or {}
    voice_rows = []
    for vid, rec in voices.items():
        if not isinstance(rec, dict):
            continue
        c = max(1, int(rec.get("count", 0)))
        avg = float(rec.get("views24_sum", 0.0)) / float(c)
        voice_rows.append((avg, vid, c))
    voice_rows.sort(reverse=True)
    for avg, vid, c in voice_rows[:10]:
        report_lines.append(f"- {vid}: avg {avg:.1f} (n={c})")
    report_lines.append("\n")

    # Best publish hours
    report_lines.append("## Publish Hour Performance (avg 24h views)\n")
    hours = state.get("performance", {}).get("publish_hours", {}) or {}
    hour_rows = []
    for hr, rec in hours.items():
        if not isinstance(rec, dict):
            continue
        c = max(1, int(rec.get("count", 0)))
        avg = float(rec.get("views24_sum", 0.0)) / float(c)
        hour_rows.append((avg, hr, c))
    hour_rows.sort(reverse=True)
    for avg, hr, c in hour_rows[:12]:
        report_lines.append(f"- {hr}:00 -> avg {avg:.1f} (n={c})")
    report_lines.append("\n")

    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    log.info("Wrote report: %s", report_path)


def main() -> None:
    cfg = load_yaml("config/config.yaml")
    setup_logging(cfg.get("logging", {}).get("level"))
    state = load_state("state/state.json")
    analyze_and_update(cfg, state)
    state["last_analyze_at"] = utcnow().isoformat().replace("+00:00", "Z")
    save_state("state/state.json", state)


if __name__ == "__main__":
    main()
