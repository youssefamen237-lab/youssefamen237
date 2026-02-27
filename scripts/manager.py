import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import load_db, save_db
from src.youtube_api import get_authenticated_service

def analyze_channel():
    print("📊 Running Manager Analysis...")
    youtube = get_authenticated_service()
    db = load_db()
    
    # Fetch latest videos stats
    request = youtube.search().list(part="snippet", forMine=True, type="video", maxResults=10)
    response = request.execute()
    
    total_views = 0
    for item in response.get("items", []):
        video_id = item["id"]["videoId"]
        stats_req = youtube.videos().list(part="statistics", id=video_id)
        stats_res = stats_req.execute()
        views = int(stats_res["items"][0]["statistics"].get("viewCount", 0))
        total_views += views
        
    db["analytics"]["last_10_videos_views"] = total_views
    
    # Simple AI Strategy adjustment logic
    if total_views > 1000:
        db["strategy"]["status"] = "Aggressive Growth"
    else:
        db["strategy"]["status"] = "Testing New Templates"
        
    save_db(db)
    print(f"✅ Analysis complete. Total recent views: {total_views}")

if __name__ == "__main__":
    analyze_channel()
