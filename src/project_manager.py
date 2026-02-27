"""
project_manager.py
Analyzes channel performance using YouTube Analytics API.
Auto-adjusts strategy: best templates, posting times, CTAs, video lengths.
Uses YT_CLIENT_ID_3 / YT_CLIENT_SECRET_3 / YT_REFRESH_TOKEN_3.
Runs weekly.
"""

import os
import json
import datetime
import random
from collections import defaultdict

from youtube_uploader import get_channel_analytics, get_video_list

STRATEGY_FILE = "data/strategy.json"
ANALYTICS_LOG = "data/analytics_log.json"


def _load_strategy() -> dict:
    defaults = {
        "best_templates": ["Multiple Choice", "True / False", "Only Geniuses"],
        "best_categories": ["general knowledge", "science and nature", "history"],
        "best_posting_hours": [9, 14, 17, 20],
        "best_cta_style": "challenge",
        "optimal_short_duration_range": [13, 18],
        "optimal_long_duration_minutes": 6,
        "best_voice": "en-US-GuyNeural",
        "top_performing_tags": ["quiz", "trivia", "challenge", "brain test"],
        "avoid_categories": [],
        "analysis_date": None,
    }
    if os.path.exists(STRATEGY_FILE):
        with open(STRATEGY_FILE, "r") as f:
            saved = json.load(f)
        defaults.update(saved)
    return defaults


def _save_strategy(strategy: dict):
    os.makedirs(os.path.dirname(STRATEGY_FILE), exist_ok=True)
    strategy["analysis_date"] = datetime.datetime.utcnow().isoformat()
    with open(STRATEGY_FILE, "w") as f:
        json.dump(strategy, f, indent=2)
    print(f"[ProjectManager] Strategy updated and saved.")


def _load_videos_log() -> list:
    log_path = "data/videos_log.json"
    if os.path.exists(log_path):
        with open(log_path, "r") as f:
            return json.load(f)
    return []


def analyze_and_update_strategy():
    """
    Main analysis function. Runs weekly.
    1. Fetches analytics from YouTube API
    2. Cross-references with local videos log
    3. Identifies best performing templates, times, CTAs
    4. Updates strategy.json
    """
    print("[ProjectManager] Starting weekly strategy analysis...")

    strategy = _load_strategy()
    videos_log = _load_videos_log()

    # Fetch live analytics
    try:
        analytics_data = get_channel_analytics(credential_set=3)
        print(f"[ProjectManager] Fetched analytics for {len(analytics_data.get('rows', []))} videos")
    except Exception as e:
        print(f"[ProjectManager] Analytics fetch failed: {e}. Using local log only.")
        analytics_data = {}

    # Build performance map from analytics
    video_performance = {}
    if analytics_data and "rows" in analytics_data:
        column_headers = [h["name"] for h in analytics_data.get("columnHeaders", [])]
        for row in analytics_data["rows"]:
            row_dict = dict(zip(column_headers, row))
            video_id = row_dict.get("video", "")
            video_performance[video_id] = {
                "views": row_dict.get("views", 0),
                "avg_view_duration": row_dict.get("averageViewDuration", 0),
                "subscribers_gained": row_dict.get("subscribersGained", 0),
                "likes": row_dict.get("likes", 0),
                "comments": row_dict.get("comments", 0),
            }

    # Cross-reference with local log
    template_scores = defaultdict(list)
    category_scores = defaultdict(list)
    hour_scores = defaultdict(list)
    cta_scores = defaultdict(list)

    for video in videos_log:
        vid_id = video.get("video_id")
        perf = video_performance.get(vid_id, {})

        # Engagement score = views * 0.5 + subs * 100 + likes * 2
        score = (
            float(perf.get("views", 0)) * 0.5 +
            float(perf.get("subscribers_gained", 0)) * 100 +
            float(perf.get("likes", 0)) * 2 +
            float(perf.get("avg_view_duration", 0)) * 0.1
        )

        template = video.get("template")
        if template:
            template_scores[template].append(score)

        category = video.get("category")
        if category:
            category_scores[category].append(score)

        hour = video.get("posted_hour")
        if hour is not None:
            hour_scores[hour].append(score)

        cta = video.get("cta_style")
        if cta:
            cta_scores[cta].append(score)

    # Compute averages
    def avg_score(d):
        return {k: sum(v) / len(v) for k, v in d.items() if v}

    template_avg = avg_score(template_scores)
    category_avg = avg_score(category_scores)
    hour_avg = avg_score(hour_scores)
    cta_avg = avg_score(cta_scores)

    # Update strategy if we have enough data
    if len(template_avg) >= 3:
        sorted_templates = sorted(template_avg.items(), key=lambda x: x[1], reverse=True)
        strategy["best_templates"] = [t[0] for t in sorted_templates[:5]]
        print(f"[ProjectManager] Best templates: {strategy['best_templates']}")

    if len(category_avg) >= 3:
        sorted_cats = sorted(category_avg.items(), key=lambda x: x[1], reverse=True)
        strategy["best_categories"] = [c[0] for c in sorted_cats[:5]]
        low_cats = [c[0] for c in sorted_cats[-3:] if c[1] < 10]
        strategy["avoid_categories"] = low_cats
        print(f"[ProjectManager] Best categories: {strategy['best_categories']}")

    if len(hour_avg) >= 4:
        sorted_hours = sorted(hour_avg.items(), key=lambda x: x[1], reverse=True)
        strategy["best_posting_hours"] = [h[0] for h in sorted_hours[:4]]
        print(f"[ProjectManager] Best hours: {strategy['best_posting_hours']}")

    if cta_avg:
        best_cta = max(cta_avg.items(), key=lambda x: x[1])
        strategy["best_cta_style"] = best_cta[0]

    # Save analytics snapshot
    analytics_snapshot = {
        "date": datetime.datetime.utcnow().isoformat(),
        "video_count": len(videos_log),
        "analytics_rows": len(video_performance),
        "template_scores": template_avg,
        "category_scores": category_avg,
        "hour_scores": {str(k): v for k, v in hour_avg.items()},
    }
    log_path = ANALYTICS_LOG
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    snapshots = []
    if os.path.exists(log_path):
        with open(log_path, "r") as f:
            snapshots = json.load(f)
    snapshots.append(analytics_snapshot)
    snapshots = snapshots[-52:]  # Keep last 52 weeks
    with open(log_path, "w") as f:
        json.dump(snapshots, f, indent=2)

    _save_strategy(strategy)
    print("[ProjectManager] Analysis complete.")
    return strategy


def get_current_strategy() -> dict:
    """Returns the current strategy. Used by shorts_runner and long_runner."""
    return _load_strategy()


def get_next_posting_time(strategy: dict, base_hour: int = None) -> int:
    """
    Returns a posting hour that varies each day.
    Never repeats the same hour on consecutive days.
    """
    best_hours = strategy.get("best_posting_hours", [9, 14, 17, 20])

    # Add ±30 min jitter by returning varied hours
    available = best_hours.copy()
    if base_hour in available and len(available) > 1:
        available.remove(base_hour)

    return random.choice(available)


if __name__ == "__main__":
    result = analyze_and_update_strategy()
    print(json.dumps(result, indent=2))
