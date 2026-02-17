import os
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from google.oauth2.credentials import Credentials
from datetime import datetime
import json

class YouTubeClient:
    def __init__(self):
        self.api_service_name = "youtube"
        self.api_version = "v3"
        self.client_secrets_file = "client_secret.json" # Must be downloaded from Google Cloud
        self.token_file = "token.json"
        self.scopes = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
        
    def get_authenticated_service(self):
        creds = None
        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(self.token_file, self.scopes)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                # In a real GitHub Action, we use Env Vars for refresh token directly
                # This is a simplified logic for local/dev or pre-configured env
                pass 
            else:
                # Fallback to Env Vars for CI/CD
                client_id = os.getenv("YT_CLIENT_ID_3")
                client_secret = os.getenv("YT_CLIENT_SECRET_3")
                refresh_token = os.getenv("YT_REFRESH_TOKEN_3")
                
                if not all([client_id, client_secret, refresh_token]):
                    raise Exception("YouTube Credentials Missing in Env")
                
                creds = Credentials(
                    None,
                    refresh_token=refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=self.scopes
                )
        
        return googleapiclient.discovery.build(self.api_service_name, self.api_version, credentials=creds)

    def upload_video(self, file_path, title, description, tags, category_id="22", privacy_status="public"):
        youtube = self.get_authenticated_service()
        
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False
            }
        }
        
        media = googleapiclient.http.MediaFileUpload(file_path, mimetype="video/mp4")
        
        try:
            request = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
            response = request.execute()
            return response['id']
        except Exception as e:
            print(f"Upload Failed: {e}")
            return None

    def get_analytics(self, days=7):
        youtube = self.get_authenticated_service()
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now()).strftime('%Y-%m-%d') # Simplified for daily check
        
        # Note: Analytics API requires specific OAuth scopes often different from Upload
        # Using Search/List as fallback for basic channel stats if Analytics scope missing
        try:
            request = youtube.channels().list(
                part="statistics",
                mine=True
            )
            response = request.execute()
            return response['items'][0]['statistics']
        except Exception as e:
            print(f"Analytics Failed: {e}")
            return {"viewCount": "0", "subscriberCount": "0"}
