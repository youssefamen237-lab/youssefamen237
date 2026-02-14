import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import *
from src.asset_manager import AssetManager

class VideoProducer:
    def __init__(self):
        self.asset_manager = AssetManager()
        self.width = 1080
        self.height = 1920

    def _create_text_image(self, text, bg_color=(0, 0, 0, 180), fontsize=60):
        """Generates a transparent image with text using PIL to avoid ImageMagick issues."""
        # Create a transparent image
        img = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
        
        # Load a default font
        try:
            font = ImageFont.truetype("arial.ttf", fontsize)
        except IOError:
            font = ImageFont.load_default()

        draw = ImageDraw.Draw(img)
        
        # Calculate text size and position (Center)
        # Use textbbox for newer Pillow versions
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (self.width - text_width) / 2
        y = (self.height - text_height) / 2
        
        # Draw background rectangle for readability (Safe Area)
        padding = 20
        rect_x0 = x - padding
        rect_y0 = y - padding
        rect_x1 = x + text_width + padding
        rect_y1 = y + text_height + padding
        draw.rectangle([rect_x0, rect_y0, rect_x1, rect_y1], fill=bg_color)
        
        # Draw text
        draw.text((x, y), text, fill="white", font=font)
        
        # Convert to numpy array for MoviePy
        return np.array(img)

    def create_short(self, content, cta):
        # 1. Prepare Assets
        bg_path = self.asset_manager.get_background_image()
        
        # Audio Generation
        q_text = content['question']
        if content.get('options'):
            opts_text = " ".join([f"Option {i+1}: {o}." for i, o in enumerate(content['options'])])
            q_text = f"{q_text} {opts_text}"
            
        q_audio_path = self.asset_manager.generate_audio(q_text)
        cta_audio_path = self.asset_manager.generate_audio(cta)
        
        # Load Audio
        q_audio = AudioFileClip(q_audio_path)
        cta_audio = AudioFileClip(cta_audio_path)
        
        # Calculate Timings
        q_dur = q_audio.duration
        cta_dur = cta_audio.duration
        timer_dur = 5.0
        answer_dur = 2.0
        
        total_dur = q_dur + cta_dur + timer_dur + answer_dur
        
        # 2. Video Composition
        # Background Clip
        bg_clip = ImageClip(bg_path).set_duration(total_dur).resize(height=self.height)
        # Ensure background covers area
        bg_clip = bg_clip.resize(lambda t: 1 + 0.01*t) # Slight zoom effect to avoid static look (optional)
        bg_clip = bg_clip.set_position("center").resize(height=self.height) # Reset resize logic to simple fit
        bg_clip = ImageClip(bg_path).set_duration(total_dur).resize(newsize=(self.width, self.height))

        # Text Clips using PIL
        # Question Text
        q_img = self._create_text_image(content['question'], fontsize=50)
        txt_question = ImageClip(q_img).set_duration(q_dur).set_start(0)

        # Timer Text
        timer_img = self._create_text_image("5", bg_color=(255, 0, 0, 150), fontsize=100)
        txt_timer = ImageClip(timer_img).set_duration(timer_dur).set_start(q_dur + cta_dur)

        # Answer Text
        ans_text = f"Answer: {content['answer']}"
        ans_img = self._create_text_image(ans_text, bg_color=(0, 100, 0, 180), fontsize=70)
        txt_answer = ImageClip(ans_img).set_duration(answer_dur).set_start(q_dur + cta_dur + timer_dur)

        # Composite Video
        video = CompositeVideoClip([bg_clip, txt_question, txt_timer, txt_answer])
        
        # Composite Audio
        audio = CompositeAudioClip([
            q_audio.set_start(0),
            cta_audio.set_start(q_dur)
            # Silence for timer and answer is implied by missing audio
        ])
        
        video = video.set_audio(audio)
        
        # 3. Export
        output_path = "output/short.mp4"
        os.makedirs("output", exist_ok=True)
        
        # Use threads for faster export
        video.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac', threads=4)
        
        # Clean up
        q_audio.close()
        cta_audio.close()
        video.close()
        
        return output_path
