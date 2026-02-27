"""
long_video_composer.py
Composes the weekly long-form video:
"The Hardest 50 Questions in 2026 - 99% of People Fail!"
Structure:
- Epic intro hook
- 50 questions in groups of 10
- Every 10 questions: motivational checkpoint encouraging likes
- Dynamic B-roll background changes every ~60 seconds
- Trivia facts after each answer
- Strong outro with subscribe CTA
Duration: 5-8 minutes
100% free tools (FFmpeg, MoviePy, edge-tts)
"""

import os
import random
import math
import tempfile
import subprocess
import shutil
import json
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from video_composer import (
    _get_font, _wrap_text, _draw_text_with_stroke,
    _load_background_frames, _get_audio_dur_ffprobe,
    WIDTH, HEIGHT, FPS, WATERMARK_TEXT
)
from tts_engine import generate_speech, get_consistent_voice
from asset_fetcher import fetch_background_video, fetch_background_music, fetch_sfx

CHECKPOINT_LINES = [
    "If you've answered 5 out of 10 correctly so far — you're officially a genius! Hit that LIKE button and let's keep going!",
    "Halfway through! If you got more than half right, you're in the top 1%! Smash that like button!",
    "You're doing amazing! Drop your score in the comments — let's see who's the quiz champion!",
    "Energy check! If you're still with me, comment 'STILL HERE' below! Let's go!",
    "Almost there! If you've made it this far, subscribe — you clearly love a challenge!",
]

INTRO_SCRIPTS = [
    "Welcome to Quiz Plus! Today we have the hardest 50 questions that will absolutely destroy your brain. Ninety nine percent of people fail at least twenty of these. Think you can beat the odds? Let's find out. No pausing allowed!",
    "Are you smarter than the average person? Today I have fifty brain-crushing questions that will test everything you know. Science, history, pop culture, you name it. Ready? Because it starts NOW.",
    "Stop scrolling. This is the ultimate quiz challenge. Fifty questions. Five minutes. Zero mercy. If you get forty or more right, drop a comment saying GENIUS. Let's begin.",
]

OUTRO_SCRIPTS = [
    "And that's all fifty questions! How many did you get right? Drop your score in the comments below. If you enjoyed this challenge, smash the subscribe button for daily quizzes. See you tomorrow!",
    "That was Quiz Plus's ultimate challenge! Comment your final score below. Subscribe now and hit the bell so you never miss a quiz. See you in the next one!",
    "Incredible work making it to the end! Only true geniuses finish this quiz. Comment your score, subscribe for more challenges, and share this with someone who thinks they're smarter than you!",
]


def _create_text_frame(text: str, bg_img: Image.Image, frame_idx: int,
                       text_color=(255, 255, 255), label: str = "",
                       label_color=(255, 220, 50)) -> Image.Image:
    """Creates a narration frame with text overlay on background."""
    frame = bg_img.copy().resize((WIDTH, HEIGHT), Image.LANCZOS)
    # Semi-transparent overlay for readability
    overlay = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 20))
    frame = Image.blend(frame, overlay, 0.55)

    draw = ImageDraw.Draw(frame)

    # Moving watermark
    wm_font = _get_font(28)
    wm_x = int(50 + (WIDTH - 250) * abs(math.sin(frame_idx * 0.01)))
    wm_y = HEIGHT - 100
    draw.text((wm_x, wm_y), WATERMARK_TEXT, font=wm_font, fill=(180, 180, 180))

    # Label (e.g. "QUESTION 5" or "ANSWER" or "DID YOU KNOW?")
    if label:
        lbl_font = _get_font(40, bold=True)
        draw.text((60, 70), label, font=lbl_font, fill=label_color)

    # Main text
    lines = _wrap_text(text, max_chars_per_line=28)
    text_font = _get_font(54, bold=False)
    line_height = 70
    total_h = len(lines) * line_height
    start_y = (HEIGHT - total_h) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=text_font)
        text_w = bbox[2] - bbox[0]
        x = (WIDTH - text_w) // 2
        y = start_y + i * line_height
        _draw_text_with_stroke(draw, (x, y), line, text_font,
                               text_color, (0, 0, 0), stroke_width=3)

    return frame


def _create_answer_reveal_frame(question: str, answer: str, trivia: str,
                                 bg_img: Image.Image, frame_idx: int) -> Image.Image:
    """Answer reveal frame with green answer and trivia."""
    frame = bg_img.copy().resize((WIDTH, HEIGHT), Image.LANCZOS)
    overlay = Image.new("RGB", (WIDTH, HEIGHT), (0, 10, 0))
    frame = Image.blend(frame, overlay, 0.6)
    draw = ImageDraw.Draw(frame)

    # "CORRECT ANSWER" label
    lbl_font = _get_font(44, bold=True)
    draw.text((60, 60), "✅ CORRECT ANSWER!", font=lbl_font, fill=(50, 255, 120))

    # Answer text
    ans_font = _get_font(66, bold=True)
    ans_lines = _wrap_text(answer, max_chars_per_line=22)
    start_y = 200
    for i, line in enumerate(ans_lines):
        bbox = draw.textbbox((0, 0), line, font=ans_font)
        text_w = bbox[2] - bbox[0]
        x = (WIDTH - text_w) // 2
        _draw_text_with_stroke(draw, (x, start_y + i * 80), line, ans_font,
                               (80, 255, 150), (0, 0, 0), stroke_width=4)

    # Trivia/fun fact
    if trivia:
        trivia_font = _get_font(36)
        trivia_lines = _wrap_text(f"💡 {trivia}", max_chars_per_line=30)
        ty_start = HEIGHT // 2 + 100
        for i, line in enumerate(trivia_lines):
            bbox = draw.textbbox((0, 0), line, font=trivia_font)
            text_w = bbox[2] - bbox[0]
            x = (WIDTH - text_w) // 2
            draw.text((x, ty_start + i * 50), line, font=trivia_font, fill=(220, 220, 255))

    # Watermark
    wm_font = _get_font(28)
    draw.text((50, HEIGHT - 100), WATERMARK_TEXT, font=wm_font, fill=(180, 180, 180))

    return frame


def _create_checkpoint_frame(checkpoint_text: str, score_hint: str,
                              bg_img: Image.Image) -> Image.Image:
    """Creates a motivational checkpoint frame."""
    frame = bg_img.copy().resize((WIDTH, HEIGHT), Image.LANCZOS)
    overlay = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 30))
    frame = Image.blend(frame, overlay, 0.6)
    draw = ImageDraw.Draw(frame)

    # Energetic border
    draw.rectangle([20, 20, WIDTH - 20, HEIGHT - 20], outline=(255, 220, 50), width=6)

    lbl_font = _get_font(52, bold=True)
    draw.text((WIDTH // 2 - 200, 80), "⭐ CHECK-IN! ⭐", font=lbl_font, fill=(255, 220, 50))

    text_font = _get_font(48)
    lines = _wrap_text(checkpoint_text, max_chars_per_line=24)
    start_y = 250
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=text_font)
        text_w = bbox[2] - bbox[0]
        x = (WIDTH - text_w) // 2
        _draw_text_with_stroke(draw, (x, start_y + i * 65), line, text_font,
                               (255, 255, 255), (0, 0, 0))

    wm_font = _get_font(28)
    draw.text((50, HEIGHT - 100), WATERMARK_TEXT, font=wm_font, fill=(180, 180, 180))
    return frame


def compose_long_video(questions: list, output_path: str) -> str:
    """
    Composes the full weekly long-form video.
    questions: list of dicts from content_generator.generate_question()
    """
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    voice = get_consistent_voice()
    frames_dir = tempfile.mkdtemp()
    audio_parts_dir = tempfile.mkdtemp()
    frame_counter = [0]
    audio_timeline = []  # [(start_time, audio_path, volume)]
    current_time = [0.0]

    def next_bg():
        return fetch_background_video()

    def add_section_to_timeline(text: str, frame_type: str, bg_img: Image.Image,
                                 audio_path: str, duration_override: float = None):
        """Adds a section (frames + audio) to the timeline."""
        audio_dur = _get_audio_dur_ffprobe(audio_path) if audio_path else 0
        section_dur = duration_override if duration_override else max(audio_dur + 0.5, 2.0)
        section_frames = int(section_dur * FPS)

        # Add audio to timeline
        if audio_path and os.path.exists(audio_path):
            audio_timeline.append((current_time[0], audio_path, 1.0))

        bg_frames = _load_background_frames(
            next_bg() if frame_counter[0] % (FPS * 60) < 3 else None,
            max(section_frames, 1)
        )

        for i in range(section_frames):
            bg_frame = bg_frames[i % len(bg_frames)]

            if frame_type == "question":
                frame = _create_text_frame(
                    text, bg_frame, frame_counter[0],
                    label=f"❓ QUESTION {int(frame_type.split('_')[-1]) if '_' in frame_type else ''}",
                    label_color=(255, 220, 50)
                )
            elif frame_type == "answer":
                frame = _create_text_frame(
                    text, bg_frame, frame_counter[0],
                    label="✅ ANSWER!", label_color=(50, 255, 120),
                    text_color=(80, 255, 150)
                )
            elif frame_type == "checkpoint":
                frame = _create_checkpoint_frame(text, "", bg_frame)
            else:  # intro, outro, narration
                frame = _create_text_frame(text, bg_frame, frame_counter[0])

            frame_path = os.path.join(frames_dir, f"frame_{frame_counter[0]:07d}.png")
            frame.save(frame_path, "PNG")
            frame_counter[0] += 1

        current_time[0] += section_dur

    # Fetch background for entire video
    bg_video = next_bg()
    bg_img_fallback = _load_background_frames(bg_video, 1)[0]

    ding_sfx = fetch_sfx("ding")
    bgm_path = fetch_background_music(duration_seconds=600)

    # === INTRO ===
    intro_text = random.choice(INTRO_SCRIPTS)
    intro_audio = os.path.join(audio_parts_dir, "intro.mp3")
    generate_speech(intro_text, intro_audio, voice_override=voice)
    add_section_to_timeline(intro_text, "narration", bg_img_fallback, intro_audio)

    # === QUESTIONS ===
    for q_idx, q in enumerate(questions[:50]):
        bg_frames = _load_background_frames(fetch_background_video(), 1)
        bg_img = bg_frames[0]

        question_num = q_idx + 1

        # Question read
        q_text = f"Question {question_num}. {q['question']}"
        q_audio = os.path.join(audio_parts_dir, f"q_{question_num}.mp3")
        generate_speech(q_text, q_audio, voice_override=voice)
        add_section_to_timeline(q['question'], "question", bg_img, q_audio)

        # Brief pause (shown as static question frame, 2s)
        add_section_to_timeline(q['question'], "question", bg_img, None, duration_override=2.0)

        # Answer reveal with ding
        a_text = f"The answer is: {q['answer']}. {q.get('trivia', '')}"
        a_audio = os.path.join(audio_parts_dir, f"a_{question_num}.mp3")
        generate_speech(a_text, a_audio, voice_override=voice)
        audio_timeline.append((current_time[0], ding_sfx, 0.8))
        add_section_to_timeline(f"ANSWER: {q['answer']}", "answer", bg_img, a_audio)

        # Checkpoint every 10 questions
        if question_num % 10 == 0 and question_num < 50:
            cp_text = random.choice(CHECKPOINT_LINES)
            cp_audio = os.path.join(audio_parts_dir, f"cp_{question_num}.mp3")
            generate_speech(cp_text, cp_audio, voice_override=voice)
            add_section_to_timeline(cp_text, "checkpoint", bg_img, cp_audio)

    # === OUTRO ===
    outro_text = random.choice(OUTRO_SCRIPTS)
    outro_audio = os.path.join(audio_parts_dir, "outro.mp3")
    generate_speech(outro_text, outro_audio, voice_override=voice)
    add_section_to_timeline(outro_text, "narration", bg_img_fallback, outro_audio)

    total_duration = current_time[0]
    total_frames = frame_counter[0]

    print(f"[LongVideo] Composed {total_frames} frames, {total_duration:.1f}s")

    # Build audio mix
    audio_mix_path = os.path.join(audio_parts_dir, "audio_mix.mp3")
    _build_long_audio_mix(audio_timeline, bgm_path, total_duration, audio_mix_path)

    # Encode video
    frames_pattern = os.path.join(frames_dir, "frame_%07d.png")
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", frames_pattern,
        "-i", audio_mix_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-movflags", "+faststart",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Long video FFmpeg failed: {result.stderr[:500]}")

    shutil.rmtree(frames_dir, ignore_errors=True)
    shutil.rmtree(audio_parts_dir, ignore_errors=True)

    print(f"[LongVideo] Encoded: {output_path}")
    return output_path


def _build_long_audio_mix(audio_timeline: list, bgm_path: str, total_duration: float, output_path: str):
    """Mixes all audio tracks with proper timing using ffmpeg."""
    inputs = []
    filter_parts = []
    labels = []
    idx = 0

    for start_time, audio_path, volume in audio_timeline:
        if audio_path and os.path.exists(audio_path):
            delay_ms = int(start_time * 1000)
            inputs += ["-i", audio_path]
            label = f"a{idx}"
            filter_parts.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms},volume={volume}[{label}]")
            labels.append(f"[{label}]")
            idx += 1

    # BGM
    if bgm_path and os.path.exists(bgm_path):
        inputs += ["-i", bgm_path]
        label = f"a{idx}"
        filter_parts.append(f"[{idx}:a]aloop=loop=-1:size=2e+09,volume=0.1[{label}]")
        labels.append(f"[{label}]")
        idx += 1

    if not labels:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
             "-t", str(total_duration), output_path],
            capture_output=True
        )
        return

    n = len(labels)
    amix = "".join(labels) + f"amix=inputs={n}:duration=longest:dropout_transition=2[aout]"
    filter_complex = ";".join(filter_parts) + ";" + amix

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-t", str(total_duration + 2),
        "-ar", "44100",
        "-ac", "2",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[LongVideo] Audio mix warning: {result.stderr[:300]}")
        # Fallback: just concatenate voice files
        if audio_timeline:
            first_audio = audio_timeline[0][1]
            if os.path.exists(first_audio):
                shutil.copy(first_audio, output_path)
