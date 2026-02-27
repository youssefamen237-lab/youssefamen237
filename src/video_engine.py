import os
import random
import requests
from moviepy.editor import *
from PIL import Image, ImageDraw
import numpy as np
from src.config import TEMP_DIR, OUTPUT_DIR, PEXELS_API_KEY, CHANNEL_NAME

def fetch_background_video():
    url = "https://api.pexels.com/videos/search?query=satisfying+kinetic+sand+soap+cutting&orientation=portrait&size=medium"
    headers = {"Authorization": PEXELS_API_KEY}
    try:
        res = requests.get(url, headers=headers).json()
        video_url = random.choice(res['videos'])['video_files'][0]['link']
        filepath = os.path.join(TEMP_DIR, "bg.mp4")
        with open(filepath, "wb") as f:
            f.write(requests.get(video_url).content)
        return filepath
    except:
        return None # Fallback to color gradient handled in builder

def create_circular_timer(duration=5, size=200):
    frames = []
    fps = 24
    total_frames = duration * fps
    for i in range(total_frames):
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        angle = 360 * (i / total_frames)
        color = "green" if i < total_frames/2 else ("orange" if i < total_frames*0.8 else "red")
        draw.arc((10, 10, size-10, size-10), start=-90, end=-90+angle, fill=color, width=15)
        frames.append(np.array(img))
    return ImageSequenceClip(frames, fps=fps)

def build_short_video(data, audio_path, timer_sfx, ding_sfx):
    q_data = data["questions"][0]
    question_text = q_data["question"]
    answer_text = q_data["answer"]
    
    # 1. Background (Split Screen Logic)
    bg_path = fetch_background_video()
    if bg_path:
        bg_clip = VideoFileClip(bg_path).resize((1080, 1920)).without_audio()
    else:
        bg_clip = ColorClip(size=(1080, 1920), color=(20, 20, 20))
    
    # 2. Audio
    voice_clip = AudioFileClip(audio_path)
    timer_audio = AudioFileClip(timer_sfx).subclip(0, 5)
    ding_audio = AudioFileClip(ding_sfx).subclip(0, 1.5)
    
    # 3. Timing
    t_question_end = voice_clip.duration
    t_timer_end = t_question_end + 5
    t_total = t_timer_end + 2 # 2 seconds for answer
    
    bg_clip = bg_clip.subclip(0, min(t_total, bg_clip.duration))
    if bg_clip.duration < t_total:
        bg_clip = bg_clip.loop(duration=t_total)

    # 4. Text Clips (Pop-up animation)
    txt_q = TextClip(question_text, fontsize=70, color='white', stroke_color='black', stroke_width=3, method='caption', size=(900, None), font="Arial-Bold")
    txt_q = txt_q.set_position(('center', 300)).set_start(0).set_end(t_timer_end).crossfadein(0.3)
    
    txt_a = TextClip(answer_text, fontsize=90, color='#00FF00', stroke_color='black', stroke_width=4, method='caption', size=(900, None), font="Arial-Bold")
    txt_a = txt_a.set_position('center').set_start(t_timer_end).set_end(t_total).crossfadein(0.1)
    
    # 5. Timer Clip
    timer_clip = create_circular_timer(duration=5).set_position(('center', 800)).set_start(t_question_end).set_end(t_timer_end)
    
    # 6. Moving Watermark
    watermark = TextClip(CHANNEL_NAME, fontsize=40, color='white', opacity=0.3, font="Arial")
    watermark = watermark.set_position(lambda t: (50 + t*20, 1800 - t*10)).set_duration(t_total)
    
    # 7. Combine Audio
    final_audio = CompositeAudioClip([
        voice_clip.set_start(0),
        timer_audio.set_start(t_question_end),
        ding_audio.set_start(t_timer_end)
    ])
    
    # 8. Render
    final_video = CompositeVideoClip([bg_clip, txt_q, timer_clip, txt_a, watermark])
    final_video = final_video.set_audio(final_audio)
    
    output_path = os.path.join(OUTPUT_DIR, "final_short.mp4")
    final_video.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac", preset="ultrafast", threads=4)
    return output_path
