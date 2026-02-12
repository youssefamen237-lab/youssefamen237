import os
import sys
import time
import random
from src.config import Config
from src.brain import Brain
from src.content_gen import ContentEngine
from src.media_engine import MediaEngine
from src.youtube_api import YouTubeUploader

def main():
    print("🚀 Starting Self-Governing AI Engine...")
    
    # 1. Initialize Brain & Check Safety
    brain = Brain()
    if brain.check_shadowban():
        print("🛑 System halted due to suspected shadowban.")
        sys.exit(0)
        
    # 2. Strategy & Content Generation
    strategy = brain.get_strategy()
    content_engine = ContentEngine(strategy)
    
    # Retry logic for generation
    script = None
    for _ in range(3):
        candidate = content_engine.generate_script()
        if candidate and not brain.is_duplicate(candidate['hash']):
            script = candidate
            break
            
    if not script:
        print("❌ Failed to generate unique content.")
        sys.exit(1)
        
    print(f"✅ Content Generated: {script['question']}")

    # 3. Media Production
    try:
        media_engine = MediaEngine(script, strategy)
        video_path = media_engine.render()
    except Exception as e:
        print(f"❌ Rendering Failed: {e}")
        sys.exit(1)

    # 4. Human Simulation Delay
    delay = random.randint(120, 600) # 2 to 10 mins
    print(f"⏳ Sleeping for {delay} seconds (Humanization)...")
    time.sleep(delay)

    # 5. Upload
    try:
        uploader = YouTubeUploader()
        title = f"{script['hook']} #shorts #trivia"
        desc = f"{script['question']}\n\nAnswer in the comments! {script['cta']}"
        tags = ["shorts", "trivia", "quiz", "riddle"]
        
        vid_id = uploader.upload_video(video_path, title, desc, tags)
        
        # 6. Record Data
        meta = {
            "id": vid_id,
            "hash": script['hash'],
            "strategy": strategy,
            "upload_time": time.time(),
            "script": script
        }
        brain.register_content(meta)
        
    except Exception as e:
        print(f"❌ Upload Failed: {e}")
        # Add to retry queue logic here (omitted for brevity)
        sys.exit(1)

    print("🎉 Cycle Complete.")

if __name__ == "__main__":
    main()
