\
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz

from autoyt.pipeline.storage import Storage
from autoyt.pipeline.youtube.read import fetch_video_stats
from autoyt.pipeline.youtube.yt_analytics import get_top_countries
from autoyt.utils.logging_utils import get_logger
from autoyt.utils.time import utc_now, to_timezone

log = get_logger("autoyt.analyst")


def _score_video(stat: Dict[str, Any], published_at: Optional[dt.datetime], now: dt.datetime) -> float:
    views = int((stat.get("statistics") or {}).get("viewCount") or 0)
    likes = int((stat.get("statistics") or {}).get("likeCount") or 0)
    comments = int((stat.get("statistics") or {}).get("commentCount") or 0)

    base = views + 3.0 * likes + 10.0 * comments

    if published_at is None:
        return base

    age_h = max(1.0, (now - published_at).total_seconds() / 3600.0)
    # views per hour-ish
    return base / math.sqrt(age_h)


def _ema_update(old: float, new: float, alpha: float = 0.25) -> float:
    if old <= 0:
        return max(0.05, new)
    return max(0.05, (1 - alpha) * old + alpha * new)


def _normalize_weights(scores: Dict[str, float], floor: float = 0.05) -> Dict[str, float]:
    # scale so average is 1.0
    if not scores:
        return {}
    vals = list(scores.values())
    avg = sum(vals) / max(1, len(vals))
    if avg <= 0:
        return {k: 1.0 for k in scores.keys()}
    out = {}
    for k, v in scores.items():
        out[k] = max(floor, v / avg)
    return out


def _country_to_timezone(country_code: str, default_tz: str) -> str:
    cc = (country_code or "").upper()
    try:
        tzs = pytz.country_timezones.get(cc) or []
        return tzs[0] if tzs else default_tz
    except Exception:
        return default_tz


def run_analyst(
    repo_root: Path,
    cfg_base: Dict[str, Any],
    cfg_state: Dict[str, Any],
    upload_profile_readonly: int = 1,
    analytics_profile: int = 3,
    lookback_days: int = 28,
) -> Dict[str, Any]:
    """
    Updates cfg_state in-place and returns it.
    """
    storage = Storage(repo_root)
    now = utc_now()

    # 1) Determine top country from YouTube Analytics (best effort)
    start = (now - dt.timedelta(days=lookback_days)).date()
    end = now.date()
    top_countries = []
    try:
        top_countries = get_top_countries(analytics_profile, start, end, max_rows=10)
    except Exception:
        top_countries = []

    if top_countries:
        best_country = top_countries[0][0]
        best_tz = _country_to_timezone(best_country, cfg_base["channel"]["default_timezone"])
        cfg_state["target_country"] = best_country
        cfg_state["target_timezone"] = best_tz
        log.info(f"Target country set to {best_country}, timezone={best_tz}")

    tz_name = cfg_state.get("target_timezone") or cfg_base["channel"]["default_timezone"]

    # 2) Load recent video logs
    logs = storage.load_video_log(max_lines=2000)
    # Filter last 60 days
    recent_logs = []
    cutoff = now - dt.timedelta(days=60)
    for r in logs:
        try:
            created = dt.datetime.fromisoformat(str(r.get("created_at")).replace("Z", "+00:00"))
        except Exception:
            continue
        if created >= cutoff:
            recent_logs.append(r)

    if not recent_logs:
        cfg_state["last_analyst_run"] = now.isoformat().replace("+00:00", "Z")
        return cfg_state

    # 3) Fetch stats for those videos (only those with video_id)
    video_ids = [str(r.get("video_id")) for r in recent_logs if r.get("video_id")]
    video_ids = list(dict.fromkeys(video_ids))  # unique
    stats = fetch_video_stats(upload_profile_readonly, video_ids)

    # 4) Compute per-video score and aggregate
    template_scores = defaultdict(list)
    voice_scores = defaultdict(list)
    hour_scores = defaultdict(list)
    music_scores = defaultdict(list)

    tz = pytz.timezone(tz_name)

    for r in recent_logs:
        vid = str(r.get("video_id") or "")
        if not vid or vid not in stats:
            continue
        s = stats[vid]
        published_str = (s.get("snippet") or {}).get("publishedAt") or ""
        published_at = None
        if published_str:
            try:
                published_at = dt.datetime.fromisoformat(published_str.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
            except Exception:
                published_at = None

        score = _score_video(s, published_at, now)

        tid = str(r.get("template_id") or "")
        vid_voice = str(r.get("voice_id") or "")
        used_music = bool(r.get("used_music"))

        if tid:
            template_scores[tid].append(score)
        if vid_voice:
            voice_scores[vid_voice].append(score)
        music_scores["music_on" if used_music else "music_off"].append(score)

        if published_at:
            local_dt = published_at.astimezone(tz)
            hour_scores[int(local_dt.hour)].append(score)

    # 5) Update weights (EMA)
    # Templates
    old_tpl = cfg_state.get("template_weights", {})
    tpl_avg = {k: (sum(v) / max(1, len(v))) for k, v in template_scores.items()}
    tpl_norm = _normalize_weights(tpl_avg)
    new_tpl = dict(old_tpl)
    for k, v in tpl_norm.items():
        new_tpl[k] = _ema_update(float(old_tpl.get(k, 1.0)), float(v), alpha=0.25)
    cfg_state["template_weights"] = new_tpl

    # Voices
    old_voice = cfg_state.get("voice_weights", {})
    voice_avg = {k: (sum(v) / max(1, len(v))) for k, v in voice_scores.items()}
    voice_norm = _normalize_weights(voice_avg)
    new_voice = dict(old_voice)
    for k, v in voice_norm.items():
        new_voice[k] = _ema_update(float(old_voice.get(k, 1.0)), float(v), alpha=0.20)
    cfg_state["voice_weights"] = new_voice

    # 6) Best post hours (top 4)
    hour_avg = {h: (sum(v) / max(1, len(v))) for h, v in hour_scores.items() if len(v) >= 2}
    if len(hour_avg) >= 4:
        best_hours = sorted(hour_avg.items(), key=lambda x: x[1], reverse=True)[:4]
        hours = sorted([h for h, _ in best_hours])
        cfg_state["schedule_hours_local"] = hours
        log.info(f"Updated schedule hours (local): {hours}")

    cfg_state["last_analyst_run"] = now.isoformat().replace("+00:00", "Z")
    return cfg_state
