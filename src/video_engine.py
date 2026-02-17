from moviepy.editor import *
from moviepy.video.tools.subtitles import SubtitlesClip
import os
import random

class VideoEngine:
    def __init__(self):
        self.font = "Arial-Bold" # Ensure font exists or use default
        self.safe_area_y = 800 # Bottom safe area for Shorts
        
    def create_short(self, script, audio_path, bg_path, output_path):
        # 1. Load Audio
        audio = AudioFileClip(audio_path)
        duration = audio.duration + 1.0 # Buffer
        
        # 2. Load Background
        bg = ImageClip(bg_path).resize(height=1920)
        bg = bg.set_duration(duration)
        
        # Apply Blur
        bg = bg.fx(vfx.blur, 5) 
        
        # 3. Create Text Overlay (Question)
        txt_clip = TextClip(
            script['question'], 
            fontsize=70, 
            color='white', 
            font=self.font, 
            stroke_color='black', 
            stroke_width=2,
            size=(900, None), 
            method='caption'
        )
        txt_clip = txt_clip.set_pos('center').set_duration(duration - 2) # Hide 2s before end
        
        # 4. Create Timer (Countdown)
        timer_clips = []
        for i in range(5, 0, -1):
            t_clip = TextClip(str(i), fontsize=150, color='red', font=self.font, stroke_color='white', stroke_width=5)
            t_clip = t_clip.set_duration(1).set_pos('center')
            timer_clips.append(t_clip)
        
        timer_seq = concatenate_videoclips(timer_clips)
        timer_seq = timer_seq.set_start(duration - 7) # Start 5s before end + 2s buffer
        
        # 5. Create Answer Overlay
        ans_text = f"Answer: {script['options'][script['correct_answer_index']]}"
        ans_clip = TextClip(ans_text, fontsize=80, color='#00FF00', font=self.font, stroke_color='black', stroke_width=2)
        ans_clip = ans_clip.set_pos('center').set_start(duration - 2).set_duration(2)
        
        # 6. Composite
        final = CompositeVideoClip([bg, txt_clip, timer_seq, ans_clip])
        final = final.set_audio(audio)
        
        # 7. Write
        final.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac')
        return output_path
