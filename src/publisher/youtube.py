"""
YouTube Publisher — handles OAuth refresh, video upload, metadata, thumbnail upload.
Uses credentials from GitHub Secrets.
Supports multiple credential sets (1, 2, 3) with automatic fallback.
"""

import os
import json
import time
import random
from pathlib import Path
import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from tenacity import retry, stop_after_attempt, wait_exponential

PUBLISHED_LOG = Path("data/published/uploads_log.json")
PUBLISHED_LOG.parent.mkdir(parents=True, exist_ok=True)

# Posting time windows (hour ranges, UTC) - varied to avoid patterns
SHORTS_TIME_WINDOWS = [
    (12, 14),   # noon-2pm UTC
    (15, 17),   # 3-5pm UTC
    (18, 20),   # 6-8pm UTC
    (20, 22),   # 8-10pm UTC
]

LONG_TIME_WINDOWS = [
    (13, 15),
    (16, 18),
    (19, 21),
]


def get_youtube_credentials(slot=3):
    """Get OAuth credentials from environment secrets"""
    slot_str = str(slot)
    client_id = os.environ.get(f"YT_CLIENT_ID_{slot_str}")
    client_secret = os.environ.get(f"YT_CLIENT_SECRET_{slot_str}")
    refresh_token = os.environ.get(f"YT_REFRESH_TOKEN_{slot_str}")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError(f"Missing YouTube credentials for slot {slot}")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube"],
    )

    # Refresh to get valid access token
    creds.refresh(Request())
    return creds


def build_youtube_service(slot=3):
    """Build authenticated YouTube service"""
    creds = get_youtube_credentials(slot)
    return build("youtube", "v3", credentials=creds)


def get_youtube_service_with_fallback():
    """Try each credential slot until one works"""
    for slot in [3, 1, 2]:
        try:
            service = build_youtube_service(slot)
            print(f"[Publisher] Connected using YT credentials slot {slot}")
            return service
        except Exception as e:
            print(f"[Publisher] Slot {slot} failed: {e}")
            continue
    raise RuntimeError("All YouTube credential slots failed")


def load_uploads_log():
    if PUBLISHED_LOG.exists():
        with open(PUBLISHED_LOG) as f:
            return json.load(f)
    return []


def save_uploads_log(log):
    with open(PUBLISHED_LOG, "w") as f:
        json.dump(log, f, indent=2)


def get_last_short_publish_time():
    log = load_uploads_log()
    shorts = [e for e in log if e.get("type") == "short"]
    if shorts:
        return shorts[-1].get("publish_time", "")
    return ""


def get_last_long_publish_time():
    log = load_uploads_log()
    longs = [e for e in log if e.get("type") == "long"]
    if longs:
        return longs[-1].get("publish_time", "")
    return ""


def pick_varied_publish_time(video_type="short"):
    """Pick a publish time that differs from recent posts"""
    windows = SHORTS_TIME_WINDOWS if video_type == "short" else LONG_TIME_WINDOWS
    window = random.choice(windows)
    hour = random.randint(window[0], window[1])
    minute = random.randint(0, 59)
    return hour, minute


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
def upload_video(service, video_path, seo_package, video_type="short"):
    """Upload video to YouTube with full metadata"""
    title = seo_package["title"]
    description = seo_package["description"]
    tags = seo_package.get("tags", [])
    category_id = seo_package.get("category_id", "27")

    body = {
        "snippet": {
            "title": title[:100],  # YouTube 100 char limit
            "description": description[:5000],  # YouTube 5000 char limit
            "tags": tags[:500],
            "categoryId": category_id,
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": seo_package.get("made_for_kids", False),
        },
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10MB chunks
    )

    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    print(f"[Publisher] Uploading: {title}")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"[Publisher] Upload progress: {pct}%")

    video_id = response["id"]
    print(f"[Publisher] Uploaded: https://youtube.com/watch?v={video_id}")
    return video_id


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
def upload_thumbnail(service, video_id, thumbnail_path):
    """Upload custom thumbnail to YouTube video"""
    if not thumbnail_path or not os.path.exists(thumbnail_path):
        print("[Publisher] No thumbnail to upload")
        return

    media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
    service.thumbnails().set(videoId=video_id, media_body=media).execute()
    print(f"[Publisher] Thumbnail uploaded for video {video_id}")


def log_upload(video_id, title, video_type, video_path, thumbnail_path):
    log = load_uploads_log()
    log.append({
        "video_id": video_id,
        "title": title,
        "type": video_type,
        "url": f"https://youtube.com/watch?v={video_id}",
        "publish_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "video_path": str(video_path),
        "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
    })
    save_uploads_log(log)


def publish_short(video_path, thumbnail_path, seo_package):
    """Full publication pipeline for a Short video"""
    print("\n[Publisher] === Publishing Short ===")

    service = get_youtube_service_with_fallback()

    try:
        video_id = upload_video(service, video_path, seo_package, "short")
    except HttpError as e:
        if e.resp.status == 403:
            print(f"[Publisher] Quota error on upload, will retry later: {e}")
            raise
        raise

    try:
        upload_thumbnail(service, video_id, thumbnail_path)
    except Exception as e:
        print(f"[Publisher] Thumbnail upload failed (non-fatal): {e}")

    log_upload(video_id, seo_package["title"], "short", video_path, thumbnail_path)

    print(f"[Publisher] Short published: https://youtube.com/shorts/{video_id}")
    return video_id


def publish_long_video(video_path, thumbnail_path, seo_package):
    """Full publication pipeline for a Long video"""
    print("\n[Publisher] === Publishing Long Video ===")

    service = get_youtube_service_with_fallback()

    try:
        video_id = upload_video(service, video_path, seo_package, "long")
    except HttpError as e:
        if e.resp.status == 403:
            print(f"[Publisher] Quota error: {e}")
            raise
        raise

    try:
        upload_thumbnail(service, video_id, thumbnail_path)
    except Exception as e:
        print(f"[Publisher] Thumbnail upload failed (non-fatal): {e}")

    log_upload(video_id, seo_package["title"], "long", video_path, thumbnail_path)

    print(f"[Publisher] Long video published: https://youtube.com/watch?v={video_id}")
    return video_id


def check_quota_remaining():
    """Estimate remaining YouTube API quota (rough check)"""
    log = load_uploads_log()
    from datetime import datetime, timedelta
    today = datetime.utcnow().date()
    today_uploads = [
        e for e in log
        if e.get("publish_time", "").startswith(str(today))
    ]
    # YouTube default quota: 10,000 units/day
    # Upload costs ~1600 units, thumbnail ~50 units
    estimated_used = len(today_uploads) * 1650
    return max(0, 10000 - estimated_used)


if __name__ == "__main__":
    quota = check_quota_remaining()
    print(f"Estimated remaining quota: {quota} units")
