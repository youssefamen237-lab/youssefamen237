from moviepy.editor import *
from moviepy.video.fx.all import blur
import random
import os
import requests
from config import Config
from PIL import Image

class VideoEditor:
    def __init__(self):
        self.bg_folder = "assets/backgrounds"
        if not os.path.exists(self.bg_folder):
            os.makedirs(self.bg_folder)
            self._download_sample_backgrounds()

    def _download_sample_backgrounds(self):
        # Download 5 random abstract backgrounds from Unsplash
        keywords = ["abstract", "technology", "dark", "gradient", "neon"]
        for i, keyword in enumerate(keywords):
            url = f"https://source.unsplash.com/1080x1920/?{keyword}&sig={i}"
            # Note: source.unsplash is deprecated, using direct logic or placeholder
            # For production, use unsplash API properly. Using placeholder for stability.
            try:
                response = requests.get(f"https://picsum.photos/1080/1920?random={i}")
                with open(f"{self.bg_folder}/bg_{i}.jpg", 'wb') as f:
                    f.write(response.content)
            except:
                pass

    def create_short(self, question_data, audio_path, output_path):
        # 1. Load Background
        bg_files = [f for f in os.listdir(self.bg_folder) if f.endswith(('.jpg', '.png'))]
        if not bg_files:
            raise Exception("No backgrounds found")
        
        bg_path = os.path.join(self.bg_folder, random.choice(bg_files))
        bg_clip = ImageClip(bg_path).set_duration(15) # Default short length
        
        # 2. Apply Blur
        bg_clip = bg_clip.fx(blur, 0.4) 

        # 3. Audio
        audio_clip = AudioFileClip(audio_path)
        duration = audio_clip.duration + 2 # Buffer
        
        # 4. Text Overlay (Question)
        txt_clip = TextClip(
            question_data["question"],
            fontsize=70,
            color='white',
            font='Arial-Bold',
            stroke_color='black',
            stroke_width=2,
            size=(1080, None),
            method='caption'
        ).set_pos('center').set_duration(5) # Show for 5 seconds

        # 5. Timer Overlay (Simple Text)
        timer_clip = TextClip(
            "5",
            fontsize=150,
            color='red',
            font='Arial-Bold'
        ).set_pos('center').set_duration(1).set_start(5)

        # 6. Answer Overlay
        ans_clip = TextClip(
            f"Answer: {question_data['answer']}",
            fontsize=80,
            color='#00FF00',
            font='Arial-Bold',
            stroke_color='black',
            stroke_width=2
        ).set_pos('center').set_duration(2).set_start(6)

        # Composite
        final = CompositeVideoClip([bg_clip, txt_clip, timer_clip, ans_clip])
        final = final.set_audio(audio_clip)
        final = final.set_duration(duration)

        # Write
        final.write_videofile(
            output_path,
            fps=24,
            codec='libx264',
            audio_codec='aac',
            threads=4
        )
        
        return output_path
