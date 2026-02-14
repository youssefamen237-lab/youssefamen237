from moviepy.editor import *
from PIL import Image
import numpy as np
from src.asset_manager import AssetManager

class VideoProducer:
    def __init__(self):
        self.asset_manager = AssetManager()

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
        bg_clip = ImageClip(bg_path).set_duration(total_dur).resize(height=1920).set_position("center")
        
        # Text Clips (Safe Area)
        def create_text(txt, duration, start, fontsize=60):
            return TextClip(txt, fontsize=fontsize, color='white', bg_color='rgba(0,0,0,0.6)', 
                            size=(1000, None), method='caption', align='center', font='Arial-Bold') \
                            .set_duration(duration).set_start(start).set_position("center")

        txt_question = create_text(content['question'], q_dur, 0)
        
        # Timer Visual
        txt_timer = TextClip("5", fontsize=150, color='red', font='Arial-Bold') \
                    .set_duration(timer_dur).set_start(q_dur + cta_dur).set_position("center")
        
        # Answer Reveal
        ans_text = f"Answer: {content['answer']}"
        txt_answer = TextClip(ans_text, fontsize=80, color='yellow', font='Arial-Bold') \
                     .set_duration(answer_dur).set_start(q_dur + cta_dur + timer_dur).set_position("center")

        # Composite
        video = CompositeVideoClip([bg_clip, txt_question, txt_timer, txt_answer])
        
        # Audio Composite
        audio = CompositeAudioClip([
            q_audio.set_start(0),
            cta_audio.set_start(q_dur),
            # Silence for timer and answer
        ])
        
        video = video.set_audio(audio)
        
        # 3. Export
        output_path = "output/short.mp4"
        os.makedirs("output", exist_ok=True)
        video.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac')
        return output_path

    def create_long_compilation(self, shorts_list):
        # Logic to stitch shorts or generate long content
        # Simplified: Concatenation of files
        clips = [VideoFileClip(s) for s in shorts_list]
        final_clip = concatenate_videoclips(clips)
        output_path = "output/long_video.mp4"
        final_clip.write_videofile(output_path, fps=24)
        return output_path
