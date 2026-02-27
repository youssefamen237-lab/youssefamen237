import os
import random
import logging
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

class YouTubeClient:
    def __init__(self, token_index=1):
        self.client_id = os.getenv(f"YT_CLIENT_ID_{token_index}")
        self.client_secret = os.getenv(f"YT_CLIENT_SECRET_{token_index}")
        self.refresh_token = os.getenv(f"YT_REFRESH_TOKEN_{token_index}")
        self.api = self._authenticate()

    def _authenticate(self):
        try:
            creds = Credentials(
                token=None,
                refresh_token=self.refresh_token,
                client_id=self.client_id,
                client_secret=self.client_secret,
                token_uri="https://oauth2.googleapis.com/token"
            )
            # Automatic dynamic Token refresher module handling expiry naturally
            creds.refresh(Request()) 
            return build('youtube', 'v3', credentials=creds)
        except Exception as e:
            logging.critical(f"YouTube OAuth Authority Failure!: {e}")
            return None

    def upload_video(self, file_path, seo_data, is_short=True):
        if not self.api: return False
        logging.info("Starting Youtube Secure Push Upload Link Process.")
        tags = seo_data.get('tags', [])
        tags.extend(["#shorts"] if is_short else ["masterclass", "top questions"])
        
        desc = seo_data.get('description', '')
        if is_short:
             # Important line ensures system grabs Shorts Algorithm explicitly 
             desc += "\n\n🔔 Subscribe @QuizPlus for Daily Challenges!\n#quiz #trivia"
        
        request_body = {
            'snippet': {
                'title': seo_data.get('title', f"Amazing Challenge #shorts")[0:100], 
                'description': desc[0:5000], 
                'tags': tags[0:15],
                'categoryId': '24' # entertainment -> safely transformative 
            },
            'status': {
                'privacyStatus': 'public', 
                'selfDeclaredMadeForKids': False, 
            },
            'recordingDetails': { 'locationDescription': 'United States' } # Geo targeting foreign audience logic specifically set USA!
        }
        
        try:
            media_file = MediaFileUpload(file_path, chunksize=-1, resumable=True, mimetype='video/mp4')
            insert_request = self.api.videos().insert(
                part=','.join(request_body.keys()),
                body=request_body,
                media_body=media_file
            )
            response = insert_request.execute()
            video_id = response.get('id')
            logging.info(f"YOUTUBE RUN SUCCESS! System uploaded globally - Video ID {video_id}.")
            return True
        except Exception as e:
             logging.error(f"Push YouTube Engine Blocked during commit to Youtube servers! Error: {e}")
             return False

    def create_community_post(self, question_text):
         """ YouTube Data API Community Post execution proxy implementation hack! """
         # For auto poll & subscriber trap generator
         try:
              request_body = {
                   "snippet": { "textDetails": {"contentText": f"🔥 Last video left 90% in shock... can you solve this?\n\n{question_text}\n\nA/ B/ C?\nSubscribe & we tell you the real answer tomorrow." } }
              }
              # Google Data API channel bulletins execution (simulates the community tab interface creation allowed by V3 credentials).
              self.api.activities().insert(part="snippet", body=request_body).execute()
              return True
         except Exception as e:
              # Warning: if activities endpoint access limits standard OAuth channels; fail over silently for auto-runner loops.
              logging.info(f"Community Trap Generator silent bypass logic fired: limits ({e})")
              return False
