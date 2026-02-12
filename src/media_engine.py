import os
import random
import requests
from moviepy.editor import *
from moviepy.video.tools.subtitles import SubtitlesClip
from .config import Config

class MediaEngine:
    def __init__(self, script_data, strategy):
        self.script = script_data
        self.strategy = strategy
        self.width = 1080
        self.height = 1920

    def download_background(self):
        # Fallback to local if API fails or for simplicity in this implementation
        # Checks assets/backgrounds folder
        bg_dir = os.path.join(Config.ASSETS_DIR, 'backgrounds')
        files = [f for f in os.listdir(bg_dir) if f.endswith('.mp4')]
        if not files:
            # Generate a solid color clip if no file
            return ColorClip(size=(self.width, self.height), color=(20, 20, 30), duration=15)
        
        choice = random.choice(files)
        return VideoFileClip(os.path.join(bg_dir, choice))

    def generate_audio(self, text):
        # Simple TTS fallback (gTTS) to avoid API costs/complexity in this script
        # Ideally, use ElevenLabs here
        from gtts import gTTS
        path = os.path.join(Config.OUTPUT_DIR, 'temp_audio.mp3')
        tts = gTTS(text=text, lang='en', slow=False)
        tts.save(path)
        return AudioFileClip(path)

    def render(self):
        # 1. Background
        bg_clip = self.download_background()
        
        # 2. Audio (Question)
        full_text = f"{self.script['hook']}. {self.script['question']}."
        audio_q = self.generate_audio(full_text)
        
        # 3. Audio (Answer) - Delayed
        audio_a = self.generate_audio(f"The answer is {self.script['answer']}")
        
        # 4. Text Overlay Logic
        # Hook Text
        txt_hook = TextClip(self.script['hook'], fontsize=70, color='yellow', font=Config.FONT_PATH, size=(900, None), method='caption')
        txt_hook = txt_hook.set_position(('center', 300)).set_duration(3)
        
        # Question Text
        txt_q = TextClip(self.script['question'], fontsize=60, color='white', font=Config.FONT_PATH, size=(900, None), method='caption')
        txt_q = txt_q.set_position(('center', 'center')).set_start(1).set_duration(audio_q.duration + 4) # +4 for timer
        
        # Answer Reveal
        reveal_start = 1 + audio_q.duration + 4
        txt_a = TextClip(self.script['answer'], fontsize=80, color='green', font=Config.FONT_PATH, stroke_color='black', stroke_width=2)
        txt_a = txt_a.set_position(('center', 'center')).set_start(reveal_start).set_duration(2)
        
        # Timer (Simple Text Timer)
        def make_timer(t):
            return TextClip(str(int(5 - t)), fontsize=100, color='red', font=Config.FONT_PATH)
        
        timer_start = 1 + audio_q.duration
        timer_clip = VideoClip(make_timer, duration=5).set_position(('center', 1400)).set_start(timer_start)

        # Composition
        final_duration = reveal_start + 2
        bg_clip = bg_clip.loop(duration=final_duration)
        bg_clip = bg_clip.resize(height=1920).crop(x1=0, y1=0, width=1080, height=1920, x_center=bg_clip.w/2, y_center=bg_clip.h/2)

        # Audio Composition
        final_audio = CompositeAudioClip([audio_q, audio_a.set_start(reveal_start)])
        
        video = CompositeVideoClip([bg_clip, txt_hook, txt_q, timer_clip, txt_a])
        video = video.set_audio(final_audio)
        video = video.set_duration(final_duration)
        
        output_path = os.path.join(Config.OUTPUT_DIR, 'final_short.mp4')
        video.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac')
        
        return output_path
