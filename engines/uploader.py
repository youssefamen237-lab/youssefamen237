import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from config import Config

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

class YouTubeUploader:
    def __init__(self):
        self.creds = None
        self._authenticate()

    def _authenticate(self):
        # Direct Authentication using Refresh Token from Secrets (No pickle needed)
        try:
            self.creds = Credentials(
                None,
                refresh_token=Config.YT_REFRESH_TOKEN,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=Config.YT_CLIENT_ID,
                client_secret=Config.YT_CLIENT_SECRET,
                scopes=SCOPES
            )
            self.youtube = build("youtube", "v3", credentials=self.creds)
        except Exception as e:
            raise Exception(f"Authentication Failed: {str(e)}")

    def upload_short(self, video_path, title, description, tags):
        body = {
            "snippet": {
                "title": title,
                "description": description + "\n\n#Shorts #Trivia #Quiz",
                "tags": tags,
                "categoryId": "24"
            },
            "status": {
                "privacyStatus": "public", 
                "selfDeclaredMadeForKids": False
            }
        }

        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        
        request = self.youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media
        )
        
        response = request.execute()
        return response['id']

    def upload_long(self, video_path, title, description, tags):
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "24"
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        request = self.youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
        response = request.execute()
        return response['id']
