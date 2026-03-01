"""
manager/strategy_optimizer.py – Quizzaro Strategy Optimizer
============================================================
Consumes enriched analytics data produced by project_manager.py
and writes an updated strategy_config.json that governs every
other module in the pipeline.

Decision logic:
  - Templates   : top 4 by mean performance score get a 3× weight boost;
                  bottom quartile gets suppressed (0.3× weight)
  - Categories  : same ranking logic, top 6 promoted
  - Voice gender: promote winner only if gap > 30%; otherwise keep "mixed"
  - Publish hours: cluster best-performing hours into [start, end] windows
  - Video duration: identify best-performing 2-second bucket; adjust target range
  - Audiences   : map top ISO-3166 country codes to audience labels
  - Daily count : scale 4–8 based on engagement rate (< 1.5% → floor; > 5% → ceiling)
  - Monetisation: track subscriber + watch-hour progress toward 1,000 / 4,000 targets

All scoring uses the weighted formula:
  score = views×1 + avg_view_pct×50 + subs_gained×100 + likes×2 + comments×3

strategy_config.json is the single source of truth read by:
  ContentEngine, TemplateEngine, PublishScheduler, QuestionBank, ProjectManager
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

STRATEGY_CONFIG_PATH = Path("data/strategy_config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "daily_video_count_min": 4,
    "daily_video_count_max": 8,
    "publish_hour_windows": [[7, 9], [12, 14], [18, 20], [21, 23]],
    "top_templates": [],
    "top_categories": [],
    "top_voice_gender": "mixed",
    "top_audiences": ["American", "British", "Canadian"],
    "target_video_duration_range": [12.0, 16.0],
    "best_cta_indices": [],
    "underperforming_templates": [],
    "underperforming_categories": [],
    "last_updated": None,
    "total_shorts_analysed": 0,
    "channel_subscribers": 0,
    "monetization_progress": {
        "subscribers_needed": 1000,
        "watch_hours_needed": 4000,
        "current_subscribers": 0,
        "current_watch_hours": 0.0,
        "subscribers_remaining": 1000,
        "watch_hours_remaining": 4000.0,
        "sub_completion_pct": 0.0,
        "watch_hours_completion_pct": 0.0,
    },
}

COUNTRY_TO_AUDIENCE: dict[str, str] = {
    "US": "American", "GB": "British", "CA": "Canadian",
    "AU": "Australian", "IE": "Irish", "NZ": "New Zealander",
    "IN": "Indian English", "NG": "Nigerian English",
    "ZA": "South African", "PH": "Filipino",
}


# ─────────────────────────────────────────────────────────────────────────────
#  Scoring
# ─────────────────────────────────────────────────────────────────────────────

def _score(entry: dict) -> float:
    return (
        entry.get("views", 0) * 1.0
        + entry.get("avg_view_percent", 0.0) * 50.0
        + entry.get("subs_gained", 0) * 100.0
        + entry.get("likes", 0) * 2.0
        + entry.get("comments", 0) * 3.0
    )


def _rank_dimension(entries: list[dict], dim: str) -> list[tuple[str, float]]:
    """Group entries by dim, compute mean score, return sorted descending."""
    groups: dict[str, list[float]] = defaultdict(list)
    for e in entries:
        key = str(e.get(dim, "")).strip()
        if key:
            groups[key].append(_score(e))
    ranked = [(k, statistics.mean(v)) for k, v in groups.items() if v]
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


def _bottom_quartile(ranked: list[tuple[str, float]]) -> list[str]:
    if len(ranked) < 4:
        return []
    cutoff = max(1, len(ranked) // 4)
    return [v for v, _ in ranked[-cutoff:]]


def _rank_publish_hours(entries: list[dict]) -> list[tuple[int, float]]:
    groups: dict[int, list[float]] = defaultdict(list)
    for e in entries:
        pub = e.get("published_at", "")
        try:
            hour = datetime.fromisoformat(pub.replace("Z", "+00:00").replace("+00:00", "")).hour
            groups[hour].append(_score(e))
        except Exception:
            continue
    ranked = [(h, statistics.mean(s)) for h, s in groups.items() if s]
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


def _hours_to_windows(hours: list[int]) -> list[list[int]]:
    if not hours:
        return DEFAULT_CONFIG["publish_hour_windows"]
    hours = sorted(hours)
    windows: list[list[int]] = []
    start = prev = hours[0]
    for h in hours[1:]:
        if h - prev > 2:
            windows.append([start, prev + 1])
            start = h
        prev = h
    windows.append([start, prev + 1])
    return windows


def _rank_durations(entries: list[dict]) -> tuple[float, float]:
    """Return (target_low, target_high) based on best-scoring 2-second bucket."""
    buckets: dict[int, list[float]] = defaultdict(list)
    for e in entries:
        dur = e.get("duration_sec", 0.0)
        if dur > 0:
            bucket_key = int(dur // 2) * 2
            buckets[bucket_key].append(_score(e))

    if not buckets:
        return (12.0, 16.0)

    best_bucket = max(buckets, key=lambda k: statistics.mean(buckets[k]))
    return (max(8.0, best_bucket - 0.5), best_bucket + 2.5)


def _engagement_rate(entries: list[dict]) -> float:
    total_views = sum(e.get("views", 0) for e in entries)
    total_interactions = sum(e.get("likes", 0) + e.get("comments", 0) for e in entries)
    if total_views == 0:
        return 0.0
    return total_interactions / total_views * 100.0


# ─────────────────────────────────────────────────────────────────────────────
#  StrategyOptimizer
# ─────────────────────────────────────────────────────────────────────────────

class StrategyOptimizer:

    def load(self) -> dict:
        if STRATEGY_CONFIG_PATH.exists():
            try:
                return json.loads(STRATEGY_CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return DEFAULT_CONFIG.copy()

    def save(self, config: dict) -> None:
        config["last_updated"] = datetime.utcnow().isoformat()
        STRATEGY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        STRATEGY_CONFIG_PATH.write_text(
            json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.success(f"[Optimizer] strategy_config.json updated.")

    def optimise(
        self,
        entries: list[dict],
        channel_stats: dict,
        geo_data: list[dict],
        watch_hours: float,
    ) -> dict:
        """
        Compute all dimension rankings and return an updated config dict.
        Does NOT write to disk — caller (ProjectManager) calls .save() explicitly.
        """
        config = self.load()

        if not entries:
            logger.warning("[Optimizer] No entries to analyse. Config unchanged.")
            return config

        # ── Templates ──────────────────────────────────────────────────────
        tmpl_rank = _rank_dimension(entries, "template")
        if tmpl_rank:
            config["top_templates"] = [t for t, _ in tmpl_rank[:4]]
            config["underperforming_templates"] = _bottom_quartile(tmpl_rank)

        # ── Categories ─────────────────────────────────────────────────────
        cat_rank = _rank_dimension(entries, "category")
        if cat_rank:
            config["top_categories"] = [c for c, _ in cat_rank[:6]]
            config["underperforming_categories"] = _bottom_quartile(cat_rank)

        # ── Voice gender ───────────────────────────────────────────────────
        gender_rank = _rank_dimension(entries, "gender")
        if len(gender_rank) >= 2:
            top_g, top_score = gender_rank[0]
            _, second_score = gender_rank[1]
            gap = (top_score - second_score) / max(top_score, 1.0)
            config["top_voice_gender"] = top_g if gap > 0.30 else "mixed"
        elif len(gender_rank) == 1:
            config["top_voice_gender"] = gender_rank[0][0]

        # ── Publish hour windows ────────────────────────────────────────────
        hour_rank = _rank_publish_hours(entries)
        if len(hour_rank) >= 4:
            top_hours = sorted([h for h, _ in hour_rank[:6]])
            windows = _hours_to_windows(top_hours)
            if windows:
                config["publish_hour_windows"] = windows

        # ── Duration range ─────────────────────────────────────────────────
        dur_lo, dur_hi = _rank_durations(entries)
        config["target_video_duration_range"] = [dur_lo, dur_hi]

        # ── Audiences from geo data ─────────────────────────────────────────
        if geo_data:
            audiences = [
                COUNTRY_TO_AUDIENCE.get(g["country"], g["country"])
                for g in geo_data[:6]
            ]
            config["top_audiences"] = [a for a in audiences if a][:4]

        # ── Daily video count ───────────────────────────────────────────────
        eng = _engagement_rate(entries)
        if eng > 5.0:
            config["daily_video_count_min"] = 6
            config["daily_video_count_max"] = 8
        elif eng < 1.5:
            config["daily_video_count_min"] = 4
            config["daily_video_count_max"] = 5
        else:
            config["daily_video_count_min"] = 4
            config["daily_video_count_max"] = 7

        # ── Channel + monetisation ──────────────────────────────────────────
        subs = channel_stats.get("subscribers", 0)
        config["channel_subscribers"] = subs
        config["total_shorts_analysed"] = len(entries)
        config["monetization_progress"] = {
            "subscribers_needed": 1000,
            "watch_hours_needed": 4000,
            "current_subscribers": subs,
            "current_watch_hours": round(watch_hours, 2),
            "subscribers_remaining": max(0, 1000 - subs),
            "watch_hours_remaining": max(0.0, round(4000 - watch_hours, 2)),
            "sub_completion_pct": round(min(100.0, subs / 10.0), 1),
            "watch_hours_completion_pct": round(min(100.0, watch_hours / 40.0), 1),
        }

        logger.info(
            f"[Optimizer] top_templates={config['top_templates']} | "
            f"top_categories={config['top_categories'][:3]} | "
            f"gender={config['top_voice_gender']} | "
            f"eng_rate={eng:.2f}% | "
            f"subs={subs:,} | watch_h={watch_hours:,.1f}"
        )

        return config
