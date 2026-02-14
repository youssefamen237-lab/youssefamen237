import google.auth.transport.requests
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from src.config import YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN

class YouTubeClient:
    def __init__(self):
        self.youtube = self.get_authenticated_service()

    def get_authenticated_service(self):
        credentials = google.oauth2.credentials.Credentials(
            token=None, # Token is fetched using refresh token
            refresh_token=YT_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=YT_CLIENT_ID,
            client_secret=YT_CLIENT_SECRET
        )
        request = google.auth.transport.requests.Request()
        credentials.refresh(request)
        return build("youtube", "v3", credentials=credentials)

    def upload_video(self, file_path, title, description, tags, category_id="22", privacy="public"):
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False
            }
        }
        
        media = MediaFileUpload(file_path, chunksize=1024*1024, resumable=True, mimetype="video/*")
        
        request = self.youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"Uploaded {int(status.progress() * 100)}%")
        
        return response['id']

    def generate_seo(self, content):
        # Simplified SEO generation
        title = f"Quiz Time! Can you answer this? #Shorts"
        desc = f"{content['question']}\n\n{content.get('explanation', 'Subscribe for more!')}\n\n#quiz #trivia #shorts"
        tags = ["quiz", "trivia", "shorts", "knowledge", "facts"]
        return title, desc, tags
