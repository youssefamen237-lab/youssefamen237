import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ai_engine import generate_content
from src.audio_engine import generate_tts, get_sfx
from src.video_engine import build_short_video
from src.youtube_api import upload_video
from src.database import add_used_question

def main():
    print("🚀 Starting Short Generation...")
    
    # 1. Generate Content
    data, template = generate_content(is_long=False)
    q_data = data["questions"][0]
    print(f"Generated Question: {q_data['question']}")
    
    # 2. Generate Audio
    cta = "If you know the answer before the 5 seconds end, drop it in the comments!"
    script = f"{q_data['question']}... {cta}"
    audio_path = generate_tts(script, "voice.mp3")
    timer_sfx = get_sfx("timer")
    ding_sfx = get_sfx("ding")
    
    # 3. Build Video
    video_path = build_short_video(data, audio_path, timer_sfx, ding_sfx)
    
    # 4. Upload to YouTube
    upload_video(
        file_path=video_path,
        title=data["seo_title"],
        description=data["seo_desc"],
        tags=data["tags"],
        is_short=True
    )
    
    # 5. Save to DB
    add_used_question(q_data["question"], template)
    print("✅ Short published successfully!")

if __name__ == "__main__":
    main()
