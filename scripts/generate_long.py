import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ai_engine import generate_content
from src.audio_engine import generate_tts, get_sfx
from src.video_engine import build_short_video
from src.youtube_api import upload_video
from moviepy.editor import concatenate_videoclips, VideoFileClip
from src.config import OUTPUT_DIR

def main():
    print("🚀 Starting Long Video Generation...")
    data, template = generate_content(is_long=True)
    
    clips = []
    timer_sfx = get_sfx("timer")
    ding_sfx = get_sfx("ding")
    
    # Process first 10 questions to keep render time under GitHub limits (approx 5 mins video)
    for i, q_data in enumerate(data["questions"][:10]):
        print(f"Processing Q{i+1}...")
        single_q_data = {"questions": [q_data]}
        audio_path = generate_tts(q_data["question"], f"voice_{i}.mp3")
        
        clip_path = build_short_video(single_q_data, audio_path, timer_sfx, ding_sfx)
        clips.append(VideoFileClip(clip_path))
        
    final_long = concatenate_videoclips(clips, method="compose")
    output_path = os.path.join(OUTPUT_DIR, "final_long.mp4")
    final_long.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac", preset="ultrafast", threads=4)
    
    upload_video(
        file_path=output_path,
        title=data["seo_title"],
        description=data["seo_desc"],
        tags=data["tags"],
        is_short=False
    )
    print("✅ Long Video published successfully!")

if __name__ == "__main__":
    main()
