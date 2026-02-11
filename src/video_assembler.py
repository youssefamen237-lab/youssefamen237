import os
import random
import textwrap
from typing import Dict
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy.editor import *
from moviepy.video.fx.all import speedx
import requests

from utils import logger

class VideoAssembler:
    def __init__(self, config: Dict):
        self.config = config
        self.width = 1080
        self.height = 1920
        self.safe_zone_top = int(self.height * 0.15)
        self.safe_zone_bottom = int(self.height * 0.20)
        
    def create(self, content: Dict, params: Dict) -> str:
        """Assemble final video"""
        try:
            duration = params['duration']
            output_path = f"output/short_{content['content_hash']}.mp4"
            os.makedirs('output', exist_ok=True)
            
            # Create components
            background = self._create_background(content, duration)
            text_clips = self._create_text_overlay(content, duration)
            audio = self._create_audio(content, params['voice_speed'])
            music = self._add_music(duration, content['timer_duration'])
            
            # Composite
            video = CompositeVideoClip([background] + text_clips, size=(self.width, self.height))
            video = video.set_audio(CompositeAudioClip([audio, music]))
            video = video.set_duration(duration)
            
            # Add timer animation
            timer = self._create_timer(content['timer_duration'], duration)
            if timer:
                video = CompositeVideoClip([video, timer])
            
            # Speed variation
            if params['voice_speed'] != 1.0:
                video = video.fx(speedx, params['voice_speed'])
                
            # Write file
            video.write_videofile(
                output_path,
                fps=24,
                codec='libx264',
                audio_codec='aac',
                threads=4,
                logger=None
            )
            
            video.close()
            return output_path
            
        except Exception as e:
            logger.error(f"Video assembly failed: {e}")
            return None
    
    def _create_background(self, content: Dict, duration: float) -> ColorClip:
        """Generate or select background"""
        # Try local assets first
        bg_dir = 'assets/backgrounds'
        if os.path.exists(bg_dir) and random.random() > 0.3:
            files = [f for f in os.listdir(bg_dir) if f.endswith(('.mp4', '.jpg', '.png'))]
            if files:
                selected = random.choice(files)
                path = os.path.join(bg_dir, selected)
                if path.endswith('.mp4'):
                    clip = VideoFileClip(path).loop(duration=duration)
                    return clip.resize((self.width, self.height))
                else:
                    img = ImageClip(path).set_duration(duration)
                    return img.resize((self.width, self.height))
        
        # Generate gradient background
        return self._generate_gradient(duration)
    
    def _generate_gradient(self, duration: float) -> ColorClip:
        """Create animated gradient"""
        # Create gradient frames
        frames = []
        colors = [random.randint(0, 255) for _ in range(6)]  # 2 RGB colors
        
        for t in np.linspace(0, duration, int(duration*24)):
            progress = t / duration
            r = int(colors[0] * (1-progress) + colors[3] * progress)
            g = int(colors[1] * (1-progress) + colors[4] * progress)
            b = int(colors[2] * (1-progress) + colors[5] * progress)
            
            img = Image.new('RGB', (self.width, self.height), (r, g, b))
            frames.append(np.array(img))
            
        return ImageSequenceClip(frames, fps=24)
    
    def _create_text_overlay(self, content: Dict, duration: float) -> list:
        """Create text elements"""
        clips = []
        
        # Hook (first 0.7s)
        hook_clip = (TextClip(content['hook'], fontsize=70, color='white', 
                             stroke_color='black', stroke_width=2, font='Arial-Bold',
                             method='caption', size=(self.width-100, None))
                    .set_position(('center', self.safe_zone_top))
                    .set_duration(0.7)
                    .set_start(0))
        clips.append(hook_clip)
        
        # Question
        question_text = content['question']
        question_clip = (TextClip(question_text, fontsize=60, color='white',
                                  stroke_color='black', stroke_width=2, font='Arial',
                                  method='caption', size=(self.width-100, None),
                                  align='center')
                        .set_position('center')
                        .set_duration(content['timer_duration'])
                        .set_start(0.7))
        clips.append(question_clip)
        
        # Options if multiple choice
        if content['template'] == 'multiple_choice' and content['options']:
            options_text = '\n'.join(content['options'])
            options_clip = (TextClip(options_text, fontsize=50, color='yellow',
                                     stroke_color='black', stroke_width=1, font='Arial',
                                     method='caption', size=(self.width-100, None))
                           .set_position(('center', self.height//2 + 100))
                           .set_duration(content['timer_duration'])
                           .set_start(0.7))
            clips.append(options_clip)
        
        # Answer (last 1-2 seconds)
        answer_duration = random.uniform(1.0, 2.0)
        answer_start = duration - answer_duration
        answer_clip = (TextClip(f"Answer: {content['answer']}", fontsize=80, color='#00FF00',
                                stroke_color='black', stroke_width=3, font='Arial-Bold')
                      .set_position('center')
                      .set_duration(answer_duration)
                      .set_start(answer_start))
        clips.append(answer_clip)
        
        # CTA
        cta_clip = (TextClip(content['cta'], fontsize=50, color='cyan',
                             stroke_color='black', stroke_width=2, font='Arial-Bold')
                   .set_position(('center', self.height - 200))
                   .set_duration(duration - 1)
                   .set_start(1))
        clips.append(cta_clip)
        
        return clips
    
    def _create_audio(self, content: Dict, speed: float) -> AudioClip:
        """Generate TTS audio"""
        text = f"{content['hook']}. {content['question']}. {content['cta']}"
        
        try:
            # Try ElevenLabs
            if os.getenv('ELEVEN_API_KEY'):
                voice_id = self.config['voice_profiles'][content['voice_gender']]['elevenlabs_voice']
                audio_path = self._elevenlabs_tts(text, voice_id)
            else:
                # Fallback to gTTS (Google TTS - free)
                from gtts import gTTS
                audio_path = f"temp_audio_{content['content_hash']}.mp3"
                tts = gTTS(text=text, lang='en', slow=False)
                tts.save(audio_path)
                
            audio = AudioFileClip(audio_path)
            
            # Speed adjustment
            if speed != 1.0:
                audio = audio.fx(vfx.speedx, speed)
                
            return audio
            
        except Exception as e:
            logger.error(f"TTS failed: {e}")
            # Return silence
            return AudioFileClip(None).set_duration(5)
    
    def _elevenlabs_tts(self, text: str, voice_id: str) -> str:
        """ElevenLabs API"""
        import requests
        
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": os.getenv('ELEVEN_API_KEY')
        }
        data = {
            "text": text[:500],  # Limit length
            "model_id": "eleven_turbo_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.5}
        }
        
        response = requests.post(url, json=data, headers=headers)
        output_path = f"temp_eleven_{hash(text)}.mp3"
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
        return output_path
    
    def _add_music(self, total_duration: float, question_duration: float) -> AudioClip:
        """Add background music that stops before answer"""
        music_dir = 'assets/music'
        if not os.path.exists(music_dir):
            return AudioClip(None).set_duration(0)
            
        files = [f for f in os.listdir(music_dir) if f.endswith(('.mp3', '.wav'))]
        if not files:
            return AudioClip(None).set_duration(0)
            
        selected = random.choice(files)
        music = AudioFileClip(os.path.join(music_dir, selected))
        
        # Loop if needed, cut to question duration only
        music = music.subclip(0, min(question_duration, music.duration))
        music = music.volumex(random.uniform(0.18, 0.27))  # 18-27% volume
        
        # Fade out
        music = music.audio_fadeout(0.5)
        
        return music
    
    def _create_timer(self, timer_duration: float, total_duration: float) -> VideoClip:
        """Visual countdown timer"""
        # Simple progress bar at bottom
        def make_frame(t):
            if t > timer_duration:
                return np.zeros((10, self.width, 3), dtype=np.uint8)
            progress = t / timer_duration
            bar_width = int(self.width * progress)
            frame = np.zeros((10, self.width, 3), dtype=np.uint8)
            frame[:, :bar_width] = [0, 255, 0]  # Green progress
            return frame
            
        return (VideoClip(make_frame, duration=timer_duration)
                .set_position(('center', self.height - 50)))
