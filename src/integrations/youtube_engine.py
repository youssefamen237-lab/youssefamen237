from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from core.config import CONFIG


class YouTubeEngine:
    def __init__(self) -> None:
        creds = Credentials(
            None,
            refresh_token=CONFIG.youtube_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=CONFIG.youtube_client_id,
            client_secret=CONFIG.youtube_client_secret,
            scopes=["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"],
        )
        self.youtube = build("youtube", "v3", credentials=creds)

    def upload(self, video_path: str, thumbnail_path: str, metadata: dict, is_short: bool) -> str:
        body = {
            "snippet": {
                "title": metadata["title"][:100],
                "description": metadata["description"][:5000],
                "tags": metadata.get("tags", [])[:25],
                "categoryId": "27",
            },
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
        }
        request = self.youtube.videos().insert(part="snippet,status", body=body, media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True))
        response = None
        while response is None:
            _, response = request.next_chunk()
        video_id = response["id"]
        self.youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path)).execute()
        return video_id

    def fetch_video_stats(self, video_id: str) -> dict:
        res = self.youtube.videos().list(part="statistics,snippet", id=video_id).execute()
        if not res["items"]:
            return {}
        item = res["items"][0]
        return {
            "video_id": video_id,
            "title": item["snippet"]["title"],
            "views": int(item["statistics"].get("viewCount", 0)),
            "likes": int(item["statistics"].get("likeCount", 0)),
            "comments": int(item["statistics"].get("commentCount", 0)),
        }
