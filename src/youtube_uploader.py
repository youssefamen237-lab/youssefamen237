"""
youtube_uploader.py
Handles YouTube Data API v3 uploads with OAuth2.
Supports multiple credentials (YT_CLIENT_ID_1/2/3).
Handles rate limiting, retries, and strike-safe metadata.
"""

import os
import json
import time
import random
import tempfile
import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# Load credentials from environment
def _get_credentials(credential_set: int = 1) -> Credentials:
    client_id = os.environ.get(f"YT_CLIENT_ID_{credential_set}", "")
    client_secret = os.environ.get(f"YT_CLIENT_SECRET_{credential_set}", "")
    refresh_token = os.environ.get(f"YT_REFRESH_TOKEN_{credential_set}", "")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError(f"Missing YouTube credentials for set {credential_set}")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube"],
    )
    return creds


def _refresh_credentials(creds: Credentials) -> Credentials:
    request = Request()
    creds.refresh(request)
    return creds


def _build_youtube_client(credential_set: int = 1):
    creds = _get_credentials(credential_set)
    creds = _refresh_credentials(creds)
    return build("youtube", "v3", credentials=creds)


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    category_id: str = "22",  # People & Blogs
    privacy: str = "public",
    is_short: bool = True,
    thumbnail_path: str = None,
    credential_set: int = 1,
    max_retries: int = 3,
) -> str:
    """
    Uploads a video to YouTube.
    Returns video ID on success.
    """
    # Sanitize metadata
    title = title[:100]
    description = description[:5000]
    tags = [t[:500] for t in tags[:15]]

    # Strike-safe: avoid misleading metadata keywords
    BANNED_TERMS = ["100% real", "leaked", "banned", "illegal", "hack", "cheat"]
    for term in BANNED_TERMS:
        title = title.replace(term, "")
        description = description.replace(term, "")

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
        },
    }

    if is_short:
        # Shorts are detected by aspect ratio + hashtag, no special API field needed
        if "#Shorts" not in description:
            description += "\n\n#Shorts #Quiz #Trivia"
        body["snippet"]["description"] = description

    last_error = None
    for attempt in range(max_retries):
        try:
            youtube = _build_youtube_client(credential_set)

            media = MediaFileUpload(
                video_path,
                mimetype="video/mp4",
                resumable=True,
                chunksize=1024 * 1024 * 5  # 5MB chunks
            )

            insert_request = youtube.videos().insert(
                part=",".join(body.keys()),
                body=body,
                media_body=media,
            )

            response = None
            while response is None:
                status, response = insert_request.next_chunk()
                if status:
                    print(f"[YTUpload] Upload progress: {int(status.progress() * 100)}%")

            video_id = response["id"]
            print(f"[YTUpload] Uploaded successfully: https://youtu.be/{video_id}")

            # Set thumbnail if provided
            if thumbnail_path and os.path.exists(thumbnail_path):
                try:
                    youtube.thumbnails().set(
                        videoId=video_id,
                        media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
                    ).execute()
                    print(f"[YTUpload] Thumbnail set for {video_id}")
                except Exception as thumb_err:
                    print(f"[YTUpload] Thumbnail failed (non-critical): {thumb_err}")

            # Rate limiting: sleep between uploads
            time.sleep(random.uniform(30, 60))

            return video_id

        except HttpError as e:
            print(f"[YTUpload] HTTP Error (attempt {attempt+1}): {e}")
            last_error = e
            if e.resp.status in [500, 502, 503, 504]:
                wait = (2 ** attempt) * 10 + random.uniform(0, 5)
                print(f"[YTUpload] Retrying in {wait:.1f}s...")
                time.sleep(wait)
            elif e.resp.status == 403:
                # Try next credential set
                credential_set = (credential_set % 2) + 1
                print(f"[YTUpload] Switching to credential set {credential_set}")
                time.sleep(5)
            elif e.resp.status == 400:
                # Bad request - don't retry
                raise
        except Exception as e:
            print(f"[YTUpload] Error (attempt {attempt+1}): {e}")
            last_error = e
            time.sleep(10 * (attempt + 1))

    raise RuntimeError(f"Upload failed after {max_retries} attempts. Last error: {last_error}")


def post_community_poll(question: str, choices: list, credential_set: int = 1) -> bool:
    """
    Posts a community poll to the YouTube channel.
    Uses YouTube Data API v3 community posts.
    """
    try:
        creds = _get_credentials(credential_set)
        creds = _refresh_credentials(creds)
        youtube = build("youtube", "v3", credentials=creds)

        # Community post with poll
        body = {
            "snippet": {
                "type": "poll",
                "pollDetails": {
                    "question": question[:200],
                    "options": [{"text": c[:50]} for c in choices[:4]],
                }
            }
        }

        response = youtube.posts().insert(part="snippet", body=body).execute()
        print(f"[CommunityPoll] Poll posted: {response.get('id', 'unknown')}")
        return True

    except Exception as e:
        print(f"[CommunityPoll] Failed: {e}")
        # Fallback: Try posting as a text post
        try:
            creds = _get_credentials(credential_set)
            creds = _refresh_credentials(creds)
            youtube = build("youtube", "v3", credentials=creds)

            poll_text = f"🧠 QUIZ TIME!\n\n{question}\n\n"
            for i, choice in enumerate(choices[:4]):
                labels = ["🅰️", "🅱️", "🅲️", "🅳️"]
                poll_text += f"{labels[i]} {choice}\n"
            poll_text += "\nComment your answer! Subscribe for daily quizzes 🎯"

            body = {
                "snippet": {
                    "type": "textOriginal",
                    "textOriginal": {"text": poll_text[:2000]}
                }
            }
            response = youtube.posts().insert(part="snippet", body=body).execute()
            print(f"[CommunityPoll] Text post fallback posted: {response.get('id', 'unknown')}")
            return True
        except Exception as e2:
            print(f"[CommunityPoll] Text post fallback also failed: {e2}")
            return False


def get_channel_analytics(credential_set: int = 3) -> dict:
    """
    Fetches channel analytics for the Project Manager.
    Uses YT_CLIENT_ID_3 / YT_CLIENT_SECRET_3 / YT_REFRESH_TOKEN_3.
    """
    try:
        creds = _get_credentials(credential_set)
        creds = _refresh_credentials(creds)
        youtube = build("youtube", "v3", credentials=creds)
        youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds)

        import datetime
        end_date = datetime.date.today().isoformat()
        start_date = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()

        # Channel ID
        channel_id = os.environ.get("YT_CHANNEL_ID", "")

        response = youtube_analytics.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="views,averageViewDuration,subscribersGained,likes,comments",
            dimensions="video",
            sort="-views",
            maxResults=50
        ).execute()

        return response

    except Exception as e:
        print(f"[Analytics] Failed to fetch analytics: {e}")
        return {}


def get_video_list(max_results: int = 50, credential_set: int = 1) -> list:
    """Returns list of recent videos from the channel."""
    try:
        youtube = _build_youtube_client(credential_set)
        channel_id = os.environ.get("YT_CHANNEL_ID", "")

        response = youtube.search().list(
            part="id,snippet",
            channelId=channel_id,
            maxResults=max_results,
            order="date",
            type="video"
        ).execute()

        return response.get("items", [])
    except Exception as e:
        print(f"[YTUpload] get_video_list failed: {e}")
        return []
