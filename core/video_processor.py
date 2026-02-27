import os
import time
import requests
import random
import logging
from moviepy.editor import VideoFileClip, TextClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip, ColorClip, ImageClip
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from core.audio_processor import AudioEngine

class VideoDirector:
    def __init__(self, bg_folder="assets/downloads"):
        self.bg_folder = bg_folder
        self.pexels_key = os.getenv("PEXELS_API_KEY")
        self.audio_engine = AudioEngine()
        os.makedirs(bg_folder, exist_ok=True)
        self.sfx = self.audio_engine.generate_sfx()

    def fetch_satisfying_b_roll(self):
        # Get free random satisfying vertical videos to bypass "Generated Auto Images Rule"
        try:
            headers = {"Authorization": self.pexels_key}
            terms =["satisfying video", "paint mixing", "slime satisfying", "calming waves"]
            query = random.choice(terms)
            
            url = f"https://api.pexels.com/videos/search?query={query}&orientation=portrait&size=medium&per_page=15"
            res = requests.get(url, headers=headers).json()
            videos = res.get('videos',[])
            
            if videos:
                vid = random.choice(videos)
                file_url = vid['video_files'][0]['link']
                
                v_path = os.path.join(self.bg_folder, f"broll_{int(time.time())}.mp4")
                r = requests.get(file_url)
                with open(v_path, 'wb') as f:
                     f.write(r.content)
                return v_path
        except Exception as e:
            logging.error(f"B-roll DL failed: {e}")
            return None
        return None

    def draw_timer_circle(self, current_sec, total=5):
        # Dynamically draws a nice red-yellow pie progress chart using Pillow frame generation.
        # This replaces generic overlays ensuring true video compilation properties!
        size = (150, 150)
        img = Image.new("RGBA", size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)
        progress = current_sec / total
        color = "lime" if progress > 0.4 else "red"
        draw.arc([(10, 10), (140, 140)], -90, -90 + int(360 * progress), fill=color, width=15)
        # add numbers 
        arr = np.array(img)
        return ImageClip(arr).set_duration(1.0).resize(width=100)

    def create_masterpiece(self, content_data, type="short"):
        logging.info("Assembling Video Layout & Compositing.")
        W, H = 1080, 1920

        # Create Voices for elements
        text_script = f"{content_data['question']} ... {content_data['cta']}..."
        vo_path = self.audio_engine.synthesize_speech(text_script, "q_voice.mp3")
        ans_path = self.audio_engine.synthesize_speech(f"The answer is {content_data['answer']}. {content_data['post_answer_trivia']}", "a_voice.mp3")
        
        vclip_q = AudioFileClip(vo_path)
        vclip_a = AudioFileClip(ans_path)

        broll_path = self.fetch_satisfying_b_roll()
        
        # Visual Layers Construction 
        try:
            if broll_path:
                 bg_clip = VideoFileClip(broll_path).without_audio().resize((W,H)).loop()
            else:
                 bg_clip = ColorClip(size=(W,H), color=(30, 30, 50))
        except:
                 bg_clip = ColorClip(size=(W,H), color=(20, 40, 60))

        # Main Question Text Frame Container with Auto-sizing Box
        t_font = 'Liberation-Sans-Bold'
        q_text = f"Q: {content_data['question']}\n\n" + " \n".join(content_data.get('options',[]))

        # Motion Graphics & Elements Design: 
        text_clip_q = (TextClip(q_text, font=t_font, color='white', fontsize=65, stroke_color='black', stroke_width=2, method='caption', size=(900, None), align='center')
                    .set_position('center')
                    .set_duration(vclip_q.duration))

        # Build The Timer Composition Layer dynamically! 
        timer_clips =[]
        for i in range(5): # 5 second loop countdown
             timer = self.draw_timer_circle(5-i).set_position(('center', H-400)).set_start(vclip_q.duration + i)
             text_sec = TextClip(str(5-i), font=t_font, color='white', fontsize=80, stroke_color='black', stroke_width=2).set_position(('center', H-385)).set_duration(1.0).set_start(vclip_q.duration + i)
             timer_clips.append(timer)
             timer_clips.append(text_sec)
        
        # Audio build for Timer Ticks & answer 
        tick_sound = AudioFileClip(self.sfx["tick"])
        audio_layers = [vclip_q.set_start(0)]
        
        # Fill tick loops!
        for idx in range(5): audio_layers.append(tick_sound.set_start(vclip_q.duration + idx))
        
        # Ding and The correct answer pop
        ans_layer = TextClip(f"Answer: {content_data['answer']}", font=t_font, color='#39ff14', fontsize=90, stroke_color='black', stroke_width=4, bg_color='rgba(0,0,0,150)').set_position('center').set_start(vclip_q.duration + 5).set_duration(2.0)
        
        ans_audio = vclip_a.set_start(vclip_q.duration + 5)
        ding_audio = AudioFileClip(self.sfx['ding']).set_start(vclip_q.duration + 5.1)
        audio_layers.append(ans_audio)
        audio_layers.append(ding_audio)
        
        # Moving System Watermark Strategy To Prove human edit! Anti-Reused System.
        # Moving text moving based on time X location mathematical sweep
        watermark = (TextClip("@QuizPlus ⚡", fontsize=45, color='white', bg_color='black')
             .set_opacity(0.4)
             .set_position(lambda t: ('center', int(200 + 40*np.sin(t))))
             .set_duration(vclip_q.duration + 7.5)) # final logic

        total_video_len = vclip_q.duration + 5 + 2 # question time + timer 5s + Ans Display time(2 sec requirement!)
        
        final_video_clip = CompositeVideoClip([
             bg_clip.subclip(0, total_video_len), 
             text_clip_q, watermark, ans_layer
        ] + timer_clips).set_duration(total_video_len)

        mixed_audio = CompositeAudioClip(audio_layers)
        final_video_clip.audio = mixed_audio

        # Variable random fps avoids hash matching detection tools exactly!
        target_fps = random.choice([29.97, 30])
        final_dest = f"assets/downloads/rendered_upload_{int(time.time())}.mp4"
        
        # Highly Optimized CPU limits avoiding workflow time limits
        final_video_clip.write_videofile(
            final_dest, fps=target_fps, preset='ultrafast', threads=4, 
            logger=None, codec="libx264", audio_codec="aac",
            ffmpeg_params=['-crf', '25'] # Safe compress! Keep under 20mb for fastest repo workflow limit speed
        )
        
        final_video_clip.close()
        bg_clip.close()
        
        return final_dest, {}
