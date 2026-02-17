from googleapiclient.discovery import build
from config import Config
from utils.database import Database

db = Database()

class ChannelManager:
    def __init__(self):
        self.youtube = build("youtube", "v3", developerKey=Config.YT_API_KEY)

    def analyze_performance(self):
        # Fetch stats for last 10 videos
        request = self.youtube.search().list(
            part="snippet",
            channelId=Config.CHANNEL_ID,
            maxResults=10,
            order="date"
        )
        response = request.execute()
        
        video_ids = [item['id']['videoId'] for item in response['items']]
        
        if not video_ids:
            return

        stats_request = self.youtube.videos().list(
            part="statistics",
            id=",".join(video_ids)
        )
        stats_response = stats_request.execute()

        for item in stats_response['items']:
            vid_id = item['id']
            views = int(item['statistics'].get('viewCount', 0))
            likes = int(item['statistics'].get('likeCount', 0))
            
            # Update DB
            # In a real scenario, we map vid_id to our internal question ID
            # Here we just log for strategy adjustment
            print(f"Video {vid_id}: {views} views")

    def adjust_strategy(self):
        # If views < 100 average -> Change Template Style
        # If CTR low -> Change Thumbnail Logic (Not implemented in this MVP)
        # This is the "Self-Governing" brain
        print("Analyzing strategy adjustments...")
        # Logic to switch preferred templates based on DB history
        pass
