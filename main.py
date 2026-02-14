import sys
import time
import random
from src.content_engine import ContentEngine
from src.video_producer import VideoProducer
from src.youtube_client import YouTubeClient
from src.utils import update_history
from datetime import datetime

def run_production_cycle(video_type="short"):
    print(f"--- Starting Production Cycle: {video_type} ---")
    
    engine = ContentEngine()
    producer = VideoProducer()
    yt = YouTubeClient()
    
    # 1. Generate Content
    content = None
    attempts = 0
    while not content and attempts < 5:
        content = engine.generate_question()
        attempts += 1
    
    if not content:
        print("Failed to generate unique content.")
        return

    cta = engine.generate_cta()
    
    # 2. Produce Video
    if video_type == "short":
        video_path = producer.create_short(content, cta)
        # SEO
        title, desc, tags = yt.generate_seo(content)
        # Add specific Short hashtags
        title = f"{content['template']} Quiz! Can you solve it?"
        
    else:
        # Logic for Long videos
        pass
    
    # 3. Upload
    try:
        video_id = yt.upload_video(video_path, title, desc, tags)
        print(f"Video Published Successfully! ID: {video_id}")
        
        # 4. Update Memory
        update_history(video_id, content['question'], content['template'], str(datetime.now()))
        
    except Exception as e:
        print(f"Upload Failed: {e}")

if __name__ == "__main__":
    # Argument parsing for GitHub Actions scheduling
    # Usage: python main.py short
    vtype = sys.argv[1] if len(sys.argv) > 1 else "short"
    run_production_cycle(vtype)
