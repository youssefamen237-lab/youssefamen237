import os
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaFileUpload
from .config import Config

class YouTubeUploader:
    def __init__(self):
        self.youtube = self.authenticate()

    def authenticate(self):
        # Authenticate using Refresh Token flow
        creds_data = {
            "client_id": Config.YT_CLIENT_ID,
            "client_secret": Config.YT_CLIENT_SECRET,
            "refresh_token": Config.YT_REFRESH_TOKEN,
            "token_uri": "https://oauth2.googleapis.com/token"
        }
        creds = Credentials.from_authorized_user_info(creds_data)
        return googleapiclient.discovery.build("youtube", "v3", credentials=creds)

    def upload_video(self, file_path, title, description, tags):
        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": tags,
                "categoryId": "22" # People & Blogs
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }

        media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
        request = self.youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"Uploaded {int(status.progress() * 100)}%")
        
        print(f"Upload Complete! Video ID: {response['id']}")
        return response['id']
