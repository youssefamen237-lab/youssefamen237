import os
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from src.config import YT_CLIENT_ID_1, YT_CLIENT_SECRET_1, YT_REFRESH_TOKEN_1

def get_authenticated_service():
    credentials = google.oauth2.credentials.Credentials(
        token=None,
        refresh_token=YT_REFRESH_TOKEN_1,
        client_id=YT_CLIENT_ID_1,
        client_secret=YT_CLIENT_SECRET_1,
        token_uri="https://oauth2.googleapis.com/token"
    )
    return build("youtube", "v3", credentials=credentials)

def upload_video(file_path, title, description, tags, is_short=True):
    youtube = get_authenticated_service()
    
    if is_short and "#Shorts" not in title:
        title += " #Shorts"
        description += "\n#Shorts #Trivia #Quiz"
        
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "24" # Entertainment
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")
            
    print(f"Upload Complete! Video ID: {response['id']}")
    return response['id']
