import os
import time
import random
import json
from engines.content_generator import ContentEngine
from engines.audio_generator import AudioEngine
from engines.video_editor import VideoEditor
from engines.uploader import YouTubeUploader
from manager.analyzer import ChannelManager
from config import Config

def main():
    print("🚀 Starting Self-Governing AI System...")
    
    try:
        # 1. Initialize Engines
        content_engine = ContentEngine()
        audio_engine = AudioEngine()
        video_engine = VideoEditor()
        uploader = YouTubeUploader()
        manager = ChannelManager()

        # 2. Generate Content
        print("🧠 Generating Question...")
        question_data = content_engine.generate_question()
        
        # 3. Generate Audio
        print("🎙️ Generating Voice...")
        audio_filename = "temp_audio.mp3"
        full_text = f"{question_data['question']} ... {question_data['cta']}"
        audio_engine.generate_audio_sync(full_text, audio_filename)
        
        # 4. Edit Video
        print("🎬 Editing Video...")
        output_filename = "output_short.mp4"
        video_engine.create_short(question_data, audio_filename, output_filename)
        
        # 5. SEO Generation
        title = f"Can You Answer This? 🤔 #{random.randint(1000,9999)}"
        description = f"Test your knowledge! \nAnswer: {question_data['answer']}"
        tags = ["trivia", "quiz", "shorts", "knowledge", "challenge"]
        
        # 6. Upload
        print("📤 Uploading to YouTube...")
        video_id = uploader.upload_short(output_filename, title, description, tags)
        print(f"✅ Uploaded Successfully! ID: {video_id}")
        
        # 7. Cleanup
        if os.path.exists(audio_filename):
            os.remove(audio_filename)
        if os.path.exists(output_filename):
            os.remove(output_filename)

        # 8. Manager Analysis
        manager.analyze_performance()

    except Exception as e:
        print(f"❌ Critical Error: {e}")
        # Fallback logic handled by GitHub Actions retry policy
        raise e

if __name__ == "__main__":
    main()
