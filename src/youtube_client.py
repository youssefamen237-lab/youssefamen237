import os
import googleapiclient.discovery
import googleapiclient.errors
from google.oauth2.credentials import Credentials

class YouTubeClient:
    def __init__(self):
        self.api_service_name = "youtube"
        self.api_version = "v3"
        self.scopes = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
        
    def get_authenticated_service(self):
        creds = None
        
        # Priority: Environment Variables (for GitHub Actions)
        client_id = os.getenv("YT_CLIENT_ID_3")
        client_secret = os.getenv("YT_CLIENT_SECRET_3")
        refresh_token = os.getenv("YT_REFRESH_TOKEN_3")
        
        if all([client_id, client_secret, refresh_token]):
            creds = Credentials(
                None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=self.scopes
            )
        else:
            # Fallback: Local Token File (for local testing)
            token_file = "token.json"
            if os.path.exists(token_file):
                creds = Credentials.from_authorized_user_file(token_file, self.scopes)
            
            if not creds or not creds.valid:
                raise Exception("YouTube Credentials Missing. Set Env Vars or token.json")
        
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
