import logging
import datetime
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .config import Config

logger = logging.getLogger("youtube_uploader")
handler = logging.FileHandler(Config.LOG_DIR / "youtube_uploader.log")
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

class YouTubeUploader:
    def __init__(self):
        self.credentials = Credentials(
            token=None,
            refresh_token=Config.YT_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=Config.YT_CLIENT_ID,
            client_secret=Config.YT_CLIENT_SECRET,
            scopes=[
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube",
                "https://www.googleapis.com/auth/yt-analytics.readonly",
            ],
        )
        self.youtube = build("youtube", "v3", credentials=self.credentials, cache_discovery=False)

    def _upload(self, video_path: Path, title: str, description: str,
                tags: list, thumbnail_path: Path, is_short: bool = False) -> str:
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "22",  # People & Blogs
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }
        if is_short:
            # Shorts are identified by #Shorts in title and vertical format (optional)
            body["snippet"]["title"] = f"{title} #Shorts"

        media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/*")
        request = self.youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"Upload progress: {int(status.progress() * 100)}%")
        video_id = response["id"]
        logger.info(f"Uploaded video ID {video_id}")

        # Upload thumbnail
        thumb_req = self.youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path))
        )
        thumb_req.execute()
        logger.info("Thumbnail uploaded.")
        return video_id

    def upload_short(self, video_path: Path, title: str, description: str,
                     tags: list, thumbnail_path: Path) -> str:
        return self._upload(video_path, title, description, tags, thumbnail_path, is_short=True)

    def upload_long(self, video_path: Path, title: str, description: str,
                    tags: list, thumbnail_path: Path) -> str:
        return self._upload(video_path, title, description, tags, thumbnail_path, is_short=False)
