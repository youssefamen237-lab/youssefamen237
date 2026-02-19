import random
import uuid
import logging
import datetime
from pathlib import Path
from moviepy.editor import (
    ImageClip,
    AudioFileClip,
    TextClip,
    CompositeVideoClip,
    concatenate_videoclips,
    VideoFileClip,
)

from .image_engine import ImageEngine
from .tts_engine import TTSEngine
from .config import Config

logger = logging.getLogger("video_builder")
handler = logging.FileHandler(Config.LOG_DIR / "video_builder.log")
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

CTA_VARIANTS = [
    "If you know the answer before the timer ends, drop it in the comments!",
    "Think you have the answer? Comment below!",
    "Got the answer? Let us know in the comments!",
    "Leave your answer in the comments before time runs out!",
    "Can you answer in 5 seconds? Comment now!",
    "Your answer goes in the comments right now!",
]

class ShortVideoBuilder:
    def __init__(self):
        self.image_engine = ImageEngine()
        self.tts_engine = TTSEngine()

    def _segment(self, bg_path: Path, text: str, duration: float, audio_path: Path = None) -> CompositeVideoClip:
        bg_clip = ImageClip(str(bg_path)).set_duration(duration)
        txt_clip = TextClip(
            txt=text,
            fontsize=70,
            font='Arial-Bold',
            color='white',
            method='caption',
            size=bg_clip.size,
            align='center'
        ).set_position('center').set_duration(duration)

        comp = CompositeVideoClip([bg_clip, txt_clip])
        if audio_path:
            audio = AudioFileClip(str(audio_path))
            comp = comp.set_audio(audio)
        return comp

    def build(self, question_data: dict) -> dict:
        """
        Generate a short video and its thumbnail.
        Returns dict with keys: video_path, thumbnail_path, title, description, tags, hashtags, cta_text
        """
        # 1️⃣ Prepare assets
        blurred_bg = self.image_engine.get_blurred_background()
        question_text = question_data['question']
        answer_text = question_data['answer']

        # 2️⃣ Generate audio
        question_audio = self.tts_engine.generate_question_audio(question_text)
        cta_text = random.choice(CTA_VARIANTS)
        cta_audio = self.tts_engine.generate_cta_audio(cta_text)

        # 3️⃣ Build video segments
        seg_q = self._segment(blurred_bg, question_text, duration=5, audio_path=question_audio)
        seg_cta = self._segment(blurred_bg, cta_text, duration=3, audio_path=cta_audio)

        # Countdown 5‑4‑3‑2‑1
        countdown_clips = []
        for num in range(5, 0, -1):
            clip = self._segment(blurred_bg, str(num), duration=1)
            countdown_clips.append(clip)
        seg_countdown = concatenate_videoclips(countdown_clips)

        # Answer reveal (no audio)
        seg_answer = self._segment(blurred_bg, answer_text, duration=1)

        # 4️⃣ Concatenate all parts
        final_clip = concatenate_videoclips([seg_q, seg_cta, seg_countdown, seg_answer])
        video_filename = f"short_{uuid.uuid4().hex}.mp4"
        video_path = Config.SHORT_VIDEO_DIR / video_filename
        final_clip.write_videofile(str(video_path), fps=30, codec='libx264', audio_codec='aac', threads=4, logger=None)

        # 5️⃣ Thumbnail (question text)
        thumbnail_path = self.image_engine.generate_thumbnail(question_text)

        logger.info(f"Short video generated at {video_path}")

        return {
            "video_path": video_path,
            "thumbnail_path": thumbnail_path,
            "question_text": question_text,
            "answer_text": answer_text,
            "cta_text": cta_text,
        }

class LongVideoBuilder:
    def __init__(self):
        self.image_engine = ImageEngine()

    def _intro_outro(self, text: str, duration: int = 5) -> VideoFileClip:
        bg = self.image_engine.get_blurred_background()
        bg_clip = ImageClip(str(bg)).set_duration(duration)
        txt_clip = TextClip(
            txt=text,
            fontsize=80,
            font='Arial-Bold',
            color='white',
            method='caption',
            size=bg_clip.size,
            align='center'
        ).set_position('center')
        comp = CompositeVideoClip([bg_clip, txt_clip])
        return comp

    def compile_long_video(self, short_video_paths: list[Path], title_text: str) -> dict:
        """
        Combine multiple Shorts into a long‑form video (>=5 minutes).
        Returns dict with keys: video_path, thumbnail_path, title, description, tags, hashtags
        """
        # Load short clips
        short_clips = [VideoFileClip(str(p)) for p in short_video_paths]
        # Intro
        intro = self._intro_outro(f"Welcome to {title_text}!", duration=6)
        # Outro (Call‑to‑action)
        outro = self._intro_outro("Enjoyed the quiz? Subscribe for more!", duration=6)

        final = concatenate_videoclips([intro] + short_clips + [outro], method="compose")
        video_filename = f"long_{uuid.uuid4().hex}.mp4"
        video_path = Config.SHORT_VIDEO_DIR.parent / "long_videos" / video_filename
        video_path.parent.mkdir(parents=True, exist_ok=True)
        final.write_videofile(str(video_path), fps=30, codec='libx264', audio_codec='aac', threads=4, logger=None)

        # Thumbnail – use first short's thumbnail content (question text)
        # We'll reuse the first short's question for thumbnail
        thumbnail_path = self.image_engine.generate_thumbnail(f"{title_text}")

        return {
            "video_path": video_path,
            "thumbnail_path": thumbnail_path,
        }
