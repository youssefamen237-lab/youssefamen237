import os
import random
import google.auth
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from utils import logger

class YouTubeUploader:
    def __init__(self):
        self.credentials = None
        self.youtube = None
        self._authenticate()
        
    def _authenticate(self):
        """OAuth2 with refresh token"""
        client_id = os.getenv('YT_CLIENT_ID_3')
        client_secret = os.getenv('YT_CLIENT_SECRET_3')
        refresh_token = os.getenv('YT_REFRESH_TOKEN_3')
        
        if not all([client_id, client_secret, refresh_token]):
            raise ValueError("Missing YouTube credentials")
            
        self.credentials = Credentials(
            None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=['https://www.googleapis.com/auth/youtube.upload',
                   'https://www.googleapis.com/auth/youtube.readonly']
        )
        
        self.credentials.refresh(Request())
        self.youtube = build('youtube', 'v3', credentials=self.credentials)
        
    def upload(self, video_path: str, content: dict, metadata: dict) -> str:
        """Upload with retries"""
        title = self._generate_title(content)
        description = self._generate_description(content)
        
        tags = ['shorts', 'brain teaser', 'trivia', 'puzzle', 
                content['template'].replace('_', ' ')]
        
        body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': tags,
                'categoryId': '24',  # Entertainment
                'defaultLanguage': 'en',
                'defaultAudioLanguage': 'en'
            },
            'status': {
                'privacyStatus': 'public',
                'selfDeclaredMadeForKids': False,
                'notifySubscribers': False  # Don't spam
            }
        }
        
        # Execute with exponential backoff
        for attempt in range(3):
            try:
                media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
                request = self.youtube.videos().insert(
                    part='snippet,status',
                    body=body,
                    media_body=media
                )
                
                response = None
                while response is None:
                    status, response = request.next_chunk()
                    if status:
                        logger.info(f"Upload {int(status.progress()*100)}%")
                        
                video_id = response['id']
                
                # Add to playlist if exists
                self._add_to_playlist(video_id, content['template'])
                
                return video_id
                
            except HttpError as e:
                logger.error(f"Upload attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    import time
                    time.sleep((2 ** attempt) * 60)  # 2min, 4min
                    
        raise Exception("Upload failed after 3 attempts")
    
    def _generate_title(self, content: dict) -> str:
        """SEO optimized title"""
        templates = [
            f"{content['hook']} 🤯",
            f"{content['hook']} #shorts",
            f"Can You Solve This? {content['template'].replace('_', ' ').title()}",
            f"Brain Teaser: {content['question'][:50]}...",
            f"Only Geniuses Know This! 🧠"
        ]
        return random.choice(templates)[:100]  # Max 100 chars
    
    def _generate_description(self, content: dict) -> str:
        return f"""{content['hook']}

🧠 Test your brain with this quick challenge!

{content['question']}

Drop your answer in the comments below! 👇

#shorts #brainteaser #trivia #{content['template']} #puzzle #iqtest"""
    
    def _add_to_playlist(self, video_id: str, template: str):
        """Auto-organize into playlists"""
        try:
            # Search for existing playlist by topic
            playlists = self.youtube.playlists().list(
                part='snippet',
                mine=True,
                maxResults=50
            ).execute()
            
            playlist_title = f"{template.replace('_', ' ').title()} Challenges"
            playlist_id = None
            
            for pl in playlists['items']:
                if pl['snippet']['title'] == playlist_title:
                    playlist_id = pl['id']
                    break
            
            # Create if not exists
            if not playlist_id:
                pl_response = self.youtube.playlists().insert(
                    part='snippet,status',
                    body={
                        'snippet': {
                            'title': playlist_title,
                            'description': f'Collection of {template} brain teasers'
                        },
                        'status': {'privacyStatus': 'public'}
                    }
                ).execute()
                playlist_id = pl_response['id']
            
            # Insert video
            self.youtube.playlistItems().insert(
                part='snippet',
                body={
                    'snippet': {
                        'playlistId': playlist_id,
                        'resourceId': {
                            'kind': 'youtube#video',
                            'videoId': video_id
                        }
                    }
                }
            ).execute()
            
        except Exception as e:
            logger.warning(f"Playlist management failed: {e}")
