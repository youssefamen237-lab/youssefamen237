"""
Analytics Engine — fetches YouTube Analytics data and updates strategy.
Tracks best performing: templates, thumbnails, CTAs, posting times, video lengths.
Uses YT_CLIENT_ID_3, YT_CLIENT_SECRET_3, YT_REFRESH_TOKEN_3 as manager credentials.
"""

import os
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from tenacity import retry, stop_after_attempt, wait_exponential

ANALYTICS_DIR = Path("data/analytics")
ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)

STRATEGY_FILE = ANALYTICS_DIR / "current_strategy.json"
PERFORMANCE_FILE = ANALYTICS_DIR / "performance_history.json"
PUBLISHED_LOG = Path("data/published/uploads_log.json")


DEFAULT_STRATEGY = {
    "best_templates": ["True / False", "Direct Question", "Only Geniuses"],
    "best_posting_hours": [14, 16, 19, 21],
    "best_categories": ["general knowledge", "science", "geography"],
    "preferred_video_length_short": 15,
    "preferred_video_length_long": 360,
    "top_performing_ctas": [],
    "last_updated": None,
    "total_videos_analyzed": 0,
    "top_views": 0,
    "avg_ctr": 0.0,
    "avg_watch_time": 0.0,
}


def get_analytics_credentials():
    """Get analytics credentials (slot 3 = manager)"""
    client_id = os.environ.get("YT_CLIENT_ID_3")
    client_secret = os.environ.get("YT_CLIENT_SECRET_3")
    refresh_token = os.environ.get("YT_REFRESH_TOKEN_3")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError("Missing analytics credentials (YT slot 3)")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=[
            "https://www.googleapis.com/auth/yt-analytics.readonly",
            "https://www.googleapis.com/auth/youtube.readonly",
        ],
    )
    creds.refresh(Request())
    return creds


def build_analytics_service():
    creds = get_analytics_credentials()
    return build("youtubeAnalytics", "v2", credentials=creds)


def build_youtube_service():
    creds = get_analytics_credentials()
    return build("youtube", "v3", credentials=creds)


def load_strategy():
    if STRATEGY_FILE.exists():
        with open(STRATEGY_FILE) as f:
            return json.load(f)
    return dict(DEFAULT_STRATEGY)


def save_strategy(strategy):
    with open(STRATEGY_FILE, "w") as f:
        json.dump(strategy, f, indent=2)


def load_performance():
    if PERFORMANCE_FILE.exists():
        with open(PERFORMANCE_FILE) as f:
            return json.load(f)
    return []


def save_performance(data):
    with open(PERFORMANCE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_uploads_log():
    if PUBLISHED_LOG.exists():
        with open(PUBLISHED_LOG) as f:
            return json.load(f)
    return []


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=2, min=5, max=20))
def fetch_video_analytics(analytics_service, channel_id, start_date, end_date):
    """Fetch analytics data from YouTube Analytics API"""
    try:
        response = analytics_service.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,likes,comments,shares,clickThroughRate",
            dimensions="video",
            sort="-views",
            maxResults=50,
        ).execute()
        return response
    except Exception as e:
        print(f"[Analytics] API error: {e}")
        return None


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=2, min=5, max=20))
def fetch_video_details(yt_service, video_ids):
    """Fetch video metadata for list of video IDs"""
    try:
        ids_str = ",".join(video_ids)
        response = yt_service.videos().list(
            part="snippet,statistics,contentDetails",
            id=ids_str,
        ).execute()
        return response.get("items", [])
    except Exception as e:
        print(f"[Analytics] Video details error: {e}")
        return []


def analyze_performance():
    """Run full analytics pipeline and update strategy"""
    print("[Analytics] Starting performance analysis...")

    channel_id = os.environ.get("YT_CHANNEL_ID")
    if not channel_id:
        print("[Analytics] No YT_CHANNEL_ID, skipping analytics")
        return load_strategy()

    try:
        analytics_svc = build_analytics_service()
        yt_svc = build_youtube_service()
    except Exception as e:
        print(f"[Analytics] Could not connect to analytics: {e}")
        return load_strategy()

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    analytics_data = fetch_video_analytics(analytics_svc, channel_id, start_date, end_date)
    if not analytics_data:
        print("[Analytics] No analytics data returned")
        return load_strategy()

    rows = analytics_data.get("rows", [])
    if not rows:
        print("[Analytics] No video rows in analytics data")
        return load_strategy()

    print(f"[Analytics] Analyzing {len(rows)} videos...")

    # Extract video IDs
    video_ids = [row[0] for row in rows if row]

    video_details = {}
    if video_ids:
        details_list = fetch_video_details(yt_svc, video_ids[:50])
        for item in details_list:
            video_details[item["id"]] = item

    # Column mapping from Analytics API
    col_headers = analytics_data.get("columnHeaders", [])
    col_map = {h["name"]: i for i, h in enumerate(col_headers)}

    performance_records = []
    for row in rows:
        vid_id = row[0]
        views = int(row[col_map.get("views", 1)] or 0) if len(row) > col_map.get("views", 1) else 0
        watch_time = float(row[col_map.get("estimatedMinutesWatched", 2)] or 0) if len(row) > col_map.get("estimatedMinutesWatched", 2) else 0
        avg_duration = float(row[col_map.get("averageViewDuration", 3)] or 0) if len(row) > col_map.get("averageViewDuration", 3) else 0
        avg_pct = float(row[col_map.get("averageViewPercentage", 4)] or 0) if len(row) > col_map.get("averageViewPercentage", 4) else 0
        subs_gained = int(row[col_map.get("subscribersGained", 5)] or 0) if len(row) > col_map.get("subscribersGained", 5) else 0
        ctr = float(row[col_map.get("clickThroughRate", 8)] or 0) if len(row) > col_map.get("clickThroughRate", 8) else 0

        title = ""
        if vid_id in video_details:
            title = video_details[vid_id].get("snippet", {}).get("title", "")

        performance_records.append({
            "video_id": vid_id,
            "title": title,
            "views": views,
            "watch_time_minutes": watch_time,
            "avg_view_duration": avg_duration,
            "avg_view_percentage": avg_pct,
            "subscribers_gained": subs_gained,
            "ctr": ctr,
            "analyzed_date": datetime.now().isoformat(),
        })

    # Save raw performance data
    existing = load_performance()
    existing_ids = {r["video_id"] for r in existing}
    for r in performance_records:
        if r["video_id"] not in existing_ids:
            existing.append(r)
    save_performance(existing)

    # Now update strategy based on findings
    strategy = update_strategy_from_performance(performance_records)
    return strategy


def update_strategy_from_performance(records):
    """Derive strategy updates from performance data"""
    strategy = load_strategy()

    if not records:
        return strategy

    # Sort by views
    sorted_by_views = sorted(records, key=lambda x: x["views"], reverse=True)
    sorted_by_pct = sorted(records, key=lambda x: x["avg_view_percentage"], reverse=True)

    # Total analytics
    total_views = sum(r["views"] for r in records)
    avg_ctr = sum(r["ctr"] for r in records) / len(records) if records else 0
    avg_watch = sum(r["avg_view_duration"] for r in records) / len(records) if records else 0
    top_views = sorted_by_views[0]["views"] if sorted_by_views else 0

    strategy["total_videos_analyzed"] = len(records)
    strategy["top_views"] = top_views
    strategy["avg_ctr"] = round(avg_ctr, 4)
    strategy["avg_watch_time"] = round(avg_watch, 2)
    strategy["last_updated"] = datetime.now().isoformat()

    # Cross-reference with uploads log to get template/category data
    uploads = load_uploads_log()
    upload_map = {u["video_id"]: u for u in uploads if "video_id" in u}

    template_performance = {}
    for r in records:
        vid_id = r["video_id"]
        if vid_id in upload_map:
            template = upload_map[vid_id].get("template", "Unknown")
            if template not in template_performance:
                template_performance[template] = {"views": 0, "count": 0}
            template_performance[template]["views"] += r["views"]
            template_performance[template]["count"] += 1

    if template_performance:
        ranked_templates = sorted(
            template_performance.items(),
            key=lambda x: x[1]["views"] / max(x[1]["count"], 1),
            reverse=True,
        )
        best_templates = [t[0] for t in ranked_templates[:4]]
        if best_templates:
            strategy["best_templates"] = best_templates
            print(f"[Analytics] Best templates: {best_templates}")

    # Posting time analysis
    hour_performance = {}
    for r in records:
        vid_id = r["video_id"]
        if vid_id in upload_map:
            pub_time = upload_map[vid_id].get("publish_time", "")
            if pub_time:
                try:
                    hour = int(pub_time[11:13])
                    if hour not in hour_performance:
                        hour_performance[hour] = {"views": 0, "count": 0}
                    hour_performance[hour]["views"] += r["views"]
                    hour_performance[hour]["count"] += 1
                except Exception:
                    pass

    if hour_performance:
        ranked_hours = sorted(
            hour_performance.items(),
            key=lambda x: x[1]["views"] / max(x[1]["count"], 1),
            reverse=True,
        )
        best_hours = [h[0] for h in ranked_hours[:4]]
        if best_hours:
            strategy["best_posting_hours"] = best_hours
            print(f"[Analytics] Best posting hours: {best_hours}")

    save_strategy(strategy)
    print(f"[Analytics] Strategy updated. Top views: {top_views}, Avg CTR: {avg_ctr:.2%}")
    return strategy


def get_current_strategy():
    return load_strategy()


def get_best_posting_time(video_type="short"):
    strategy = load_strategy()
    hours = strategy.get("best_posting_hours", [14, 16, 19, 21])
    return random.choice(hours)


if __name__ == "__main__":
    strategy = analyze_performance()
    print(json.dumps(strategy, indent=2))
