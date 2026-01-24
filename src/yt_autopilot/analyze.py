\
import json
import logging
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .db import get_uploaded_videos
from .logging_utils import setup_logging
from .settings import DATA_DIR, load_config, load_secrets
from .utils.git_utils import git_config_user, git_commit_push
from .youtube_analytics import build_analytics_client, get_hourly_views, get_video_metrics
from .youtube_auth import OAuthCandidate

logger = logging.getLogger(__name__)


def _analysis_oauth_candidates(secrets: Any) -> List[OAuthCandidate]:
    cands: List[OAuthCandidate] = []
    if secrets.yt_client_id_3 and secrets.yt_refresh_token_3:
        if secrets.yt_client_secret_3:
            cands.append(OAuthCandidate(secrets.yt_client_id_3, secrets.yt_client_secret_3, secrets.yt_refresh_token_3))
        elif secrets.yt_client_secret_1:
            cands.append(OAuthCandidate(secrets.yt_client_id_3, secrets.yt_client_secret_1, secrets.yt_refresh_token_3))

    if not cands and secrets.yt_client_id_1 and secrets.yt_client_secret_1 and secrets.yt_refresh_token_1:
        cands.append(OAuthCandidate(secrets.yt_client_id_1, secrets.yt_client_secret_1, secrets.yt_refresh_token_1))

    if not cands:
        raise RuntimeError("Missing YouTube OAuth secrets for analytics (client id/secret/refresh token)")
    return cands


def _norm_scores(scores: Dict[str, float]) -> Dict[str, float]:
    if not scores:
        return {}
    vals = [v for v in scores.values() if v is not None and v >= 0]
    if not vals:
        return {}
    min_v = min(vals)
    max_v = max(vals)
    if math.isclose(min_v, max_v):
        return {k: 1.0 for k in scores}
    out = {}
    for k, v in scores.items():
        out[k] = (float(v) - min_v) / (max_v - min_v) + 0.2  # keep >0
    return out


def _blend(old: Dict[str, float], new: Dict[str, float], alpha: float) -> Dict[str, float]:
    out = dict(old or {})
    for k, nv in (new or {}).items():
        ov = float(out.get(k, 1.0))
        out[k] = max(0.05, (1 - alpha) * ov + alpha * float(nv))
    return out


def _write_overrides(overrides: Dict[str, Any]) -> None:
    path = DATA_DIR / "runtime_overrides.json"
    doc = {"updated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "overrides": overrides}
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")


def run() -> None:
    setup_logging("analyze")
    secrets = load_secrets()
    base_config = load_config()  # includes prior overrides
    analysis_cfg = base_config.get("analysis") or {}
    lookback_days = int(analysis_cfg.get("lookback_days", 28))
    alpha = float(analysis_cfg.get("weight_update_alpha", 0.35))
    top_hours_count = int(analysis_cfg.get("top_hours_count", 8))
    min_videos = int(analysis_cfg.get("min_videos_for_weight_update", 5))

    cands = _analysis_oauth_candidates(secrets)
    yt = build_analytics_client(cands)

    uploaded = get_uploaded_videos(days=max(lookback_days, 35))
    if not uploaded:
        logger.info("No uploaded videos in DB to analyze")
        return

    # Hourly views
    hourly = get_hourly_views(yt, lookback_days=lookback_days)
    top_hours = sorted(hourly.items(), key=lambda kv: kv[1], reverse=True)[:top_hours_count]
    top_hours_list = [int(h) for h, _ in top_hours]

    # Video metrics
    per_video: List[Dict[str, Any]] = []
    for u in uploaded:
        vid = u.get("video_id")
        if not vid:
            continue
        m = get_video_metrics(yt, str(vid), lookback_days=lookback_days)
        if not m:
            continue
        row = dict(u)
        row.update(m)
        per_video.append(row)

    # Save report
    report_path = DATA_DIR / "daily_report.json"
    report_path.write_text(json.dumps({"generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "top_hours_utc": top_hours_list, "videos": per_video[:200]}, indent=2, ensure_ascii=False), encoding="utf-8")

    if len(per_video) < min_videos:
        logger.info("Not enough videos for weight updates (%s < %s)", len(per_video), min_videos)
        overrides = {"analysis": {"learned": {"top_hours_utc": top_hours_list}}}
        _write_overrides(overrides)
        git_config_user()
        git_commit_push("chore: daily analytics update", paths=["data/runtime_overrides.json", "data/daily_report.json"])
        return

    # compute retention proxy
    def retention(v: Dict[str, Any]) -> float:
        dur = float(v.get("duration_seconds") or 0.0)
        avd = float(v.get("averageViewDuration") or 0.0)
        if dur <= 0.0:
            return 0.0
        return max(0.0, min(1.5, avd / dur))

    # group scores
    voice_scores = defaultdict(list)
    template_scores = defaultdict(list)
    cta_scores = defaultdict(list)

    for v in per_video:
        score = retention(v) * (1.0 + math.log1p(float(v.get("views") or 0.0)) / 10.0)
        voice = str(v.get("voice_id") or "")
        tmpl = str(v.get("template_id") or "")
        cta = str(v.get("cta_id") or "")
        if voice:
            voice_scores[voice].append(score)
        if tmpl:
            template_scores[tmpl].append(score)
        if cta:
            cta_scores[cta].append(score)

    voice_avg = {k: sum(vals) / max(1, len(vals)) for k, vals in voice_scores.items()}
    tmpl_avg = {k: sum(vals) / max(1, len(vals)) for k, vals in template_scores.items()}
    cta_avg = {k: sum(vals) / max(1, len(vals)) for k, vals in cta_scores.items()}

    voice_new = _norm_scores(voice_avg)
    tmpl_new = _norm_scores(tmpl_avg)
    cta_new = _norm_scores(cta_avg)

    old_voice = ((base_config.get("voices") or {}).get("weights") or {})
    old_tmpl = ((base_config.get("templates") or {}).get("weights") or {})
    old_cta = ((base_config.get("cta") or {}).get("weights") or {})

    blended_voice = _blend({k: float(v) for k, v in old_voice.items()}, voice_new, alpha)
    blended_tmpl = _blend({k: float(v) for k, v in old_tmpl.items()}, tmpl_new, alpha)
    blended_cta = _blend({k: float(v) for k, v in old_cta.items()}, cta_new, alpha)

    overrides = {
        "analysis": {"learned": {"top_hours_utc": top_hours_list}},
        "voices": {"weights": blended_voice},
        "templates": {"weights": blended_tmpl},
        "cta": {"weights": blended_cta},
    }
    _write_overrides(overrides)

    git_config_user()
    git_commit_push("chore: daily analytics update", paths=["data/runtime_overrides.json", "data/daily_report.json"])
    logger.info("Analysis done. Updated weights + top_hours=%s", top_hours_list)


if __name__ == "__main__":
    run()
