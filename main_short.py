import os
import asyncio
import random
from src.content_engine import ContentEngine
from src.asset_engine import AssetEngine
from src.video_engine import VideoEngine
from src.youtube_client import YouTubeClient
from src.manager import Manager
from dotenv import load_dotenv

load_dotenv()

def main():
    print("🚀 Starting Shorts Engine...")
    
    # 1. Generate Content
    engine = ContentEngine()
    script = engine.generate_short_content()
    seo = engine.generate_seo(script['question'])
    
    # 2. Generate Assets
    asset_engine = AssetEngine()
    audio_path = "temp_audio.mp3"
    bg_path = "temp_bg.jpg"
    
    # Add CTA to audio text
    cta_options = ["Subscribe for more!", "Comment your answer!", "Did you know this?"]
    full_text = f"{script['question']} ... {random.choice(cta_options)}"
    
    asyncio.run(asset_engine.generate_voice(full_text, audio_path))
    asset_engine.get_background_image(script['category'], bg_path)
    
    # 3. Edit Video
    video_engine = VideoEngine()
    output_path = "final_short.mp4"
    video_engine.create_short(script, audio_path, bg_path, output_path)
    
    # 4. Upload
    yt = YouTubeClient()
    title = random.choice(seo['titles'])
    desc = f"{seo['description']}\n\n#shorts #quiz #{script['category'].lower()}"
    
    video_id = yt.upload_video(output_path, title, desc, seo['tags'])
    
    if video_id:
        print(f"✅ Uploaded Successfully: {video_id}")
        # Cleanup
        os.remove(audio_path)
        os.remove(bg_path)
        os.remove(output_path)
    else:
        print("❌ Upload Failed")

if __name__ == "__main__":
    main()
