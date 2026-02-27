"""
video_composer.py
Composes YouTube Shorts videos:
- Split-screen (question top, satisfying video bottom)
- Circular countdown timer (green → red)
- Question text animation (pop-in)
- Answer reveal with SFX
- Moving watermark "Quiz Plus"
- Random duration variation for anti-spam fingerprinting
All using MoviePy + Pillow + FFmpeg. 100% free.
"""

import os
import random
import math
import tempfile
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import json

# Resolution: 1080x1920 (9:16 vertical)
WIDTH = 1080
HEIGHT = 1920
FPS = 30
FONT_DIR = "assets/fonts"
WATERMARK_TEXT = "@QuizPlus"
CHANNEL_NAME = "Quiz Plus"


def _get_font(size: int, bold: bool = False):
    """Returns a PIL font. Downloads DejaVu if not cached."""
    os.makedirs(FONT_DIR, exist_ok=True)
    font_path = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")

    if not os.path.exists(font_path):
        # Use system font fallback
        try:
            import subprocess
            result = subprocess.run(["fc-list", ":spacing=100"], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout:
                system_fonts = result.stdout.strip().split("\n")
                if system_fonts:
                    parts = system_fonts[0].split(":")
                    if parts:
                        font_path = parts[0].strip()
        except Exception:
            pass

    try:
        return ImageFont.truetype(font_path, size)
    except Exception:
        return ImageFont.load_default()


def _wrap_text(text: str, max_chars_per_line: int = 28) -> list:
    """Wraps text into lines."""
    words = text.split()
    lines = []
    current = []
    current_len = 0
    for word in words:
        if current_len + len(word) + 1 > max_chars_per_line and current:
            lines.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += len(word) + 1
    if current:
        lines.append(" ".join(current))
    return lines


def _draw_text_with_stroke(draw, xy, text, font, fill, stroke_fill, stroke_width=4):
    """Draws text with outline/stroke effect for readability on any background."""
    x, y = xy
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=stroke_fill)
    draw.text((x, y), text, font=font, fill=fill)


def _draw_circular_timer(img: Image.Image, frame_idx: int, total_frames: int,
                          cx: int, cy: int, radius: int = 80) -> Image.Image:
    """
    Draws a circular countdown timer that shrinks from full circle to empty.
    Color transitions from green to yellow to red.
    """
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    progress = 1.0 - (frame_idx / max(total_frames - 1, 1))

    # Background circle
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=(0, 0, 0, 140),
        outline=(255, 255, 255, 180),
        width=4
    )

    # Progress arc: green → yellow → red
    if progress > 0.6:
        arc_color = (50, 220, 50, 255)
    elif progress > 0.3:
        r_val = int(255 * (1 - (progress - 0.3) / 0.3))
        arc_color = (255, 200, 0, 255)
    else:
        arc_color = (255, 50, 50, 255)

    angle_end = -90 + int(360 * progress)
    if progress > 0.01:
        draw.arc(
            [cx - radius + 6, cy - radius + 6, cx + radius - 6, cy + radius - 6],
            start=-90,
            end=angle_end,
            fill=arc_color,
            width=10
        )

    # Number in center
    seconds_left = math.ceil(progress * 5)
    seconds_left = max(0, min(5, seconds_left))
    font = _get_font(52, bold=True)
    num_text = str(seconds_left)
    bbox = draw.textbbox((0, 0), num_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    draw.text((cx - text_w // 2, cy - text_h // 2), num_text, font=font, fill=(255, 255, 255, 255))

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _create_question_frame(question_text: str, choices: list, template: str,
                            bg_image: Image.Image, frame_idx: int, total_frames: int,
                            timer_cx: int, timer_cy: int, pop_in_frames: int = 8) -> Image.Image:
    """
    Creates a single frame of the question display.
    Top half: blurred background + question text
    Bottom half: video (bg_image is the full frame)
    """
    frame = bg_image.copy().resize((WIDTH, HEIGHT), Image.LANCZOS)

    # Darken top half for readability
    overlay = Image.new("RGBA", (WIDTH, HEIGHT // 2), (0, 0, 0, 160))
    frame.paste(Image.fromarray(np.array(overlay)[..., :3]), (0, 0))

    draw = ImageDraw.Draw(frame)

    # Pop-in animation for text
    if frame_idx < pop_in_frames:
        scale = 0.7 + 0.3 * (frame_idx / pop_in_frames)
    else:
        scale = 1.0

    # Template label
    template_font = _get_font(max(20, int(28 * scale)))
    template_color = (255, 220, 50)
    _draw_text_with_stroke(draw, (WIDTH // 2 - 100, 60), f"🎯 {template.upper()}", template_font,
                           template_color, (0, 0, 0))

    # Question text
    lines = _wrap_text(question_text, max_chars_per_line=26)
    q_font = _get_font(max(36, int(52 * scale)), bold=True)
    line_height = max(50, int(65 * scale))
    total_text_height = len(lines) * line_height
    start_y = max(120, (HEIGHT // 2 - total_text_height) // 2 + 50)

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=q_font)
        text_w = bbox[2] - bbox[0]
        x = (WIDTH - text_w) // 2
        y = start_y + i * line_height
        _draw_text_with_stroke(draw, (x, y), line, q_font, (255, 255, 255), (0, 0, 0), stroke_width=3)

    # Choices for Multiple Choice
    if choices and template == "Multiple Choice":
        choice_font = _get_font(32, bold=False)
        choice_colors = [(50, 200, 255), (255, 150, 50), (100, 255, 100), (255, 100, 150)]
        choice_labels = ["A", "B", "C", "D"]
        choice_start_y = HEIGHT // 2 + 40
        for idx, (label, choice) in enumerate(zip(choice_labels, choices[:4])):
            cy_pos = choice_start_y + idx * 55
            rect_color = choice_colors[idx % len(choice_colors)]
            # Draw choice pill
            draw.rounded_rectangle(
                [60, cy_pos - 5, WIDTH - 60, cy_pos + 45],
                radius=12,
                fill=(0, 0, 0, 180),
                outline=rect_color,
                width=2
            )
            _draw_text_with_stroke(draw, (80, cy_pos + 5), f"{label}. {choice}", choice_font,
                                   (255, 255, 255), (0, 0, 0), stroke_width=2)

    # Draw circular timer
    frame = _draw_circular_timer(frame, frame_idx, total_frames, timer_cx, timer_cy)

    # Moving watermark
    wm_font = _get_font(24)
    wm_alpha = 80  # 30% opacity equivalent
    wm_x = int(50 + (WIDTH - 200) * abs(math.sin(frame_idx * 0.02)))
    wm_y = int(HEIGHT - 120 + 30 * abs(math.cos(frame_idx * 0.015)))
    draw2 = ImageDraw.Draw(frame)
    _draw_text_with_stroke(draw2, (wm_x, wm_y), WATERMARK_TEXT, wm_font,
                           (255, 255, 255, 80), (0, 0, 0, 40), stroke_width=1)

    return frame


def _create_answer_frame(answer_text: str, bg_image: Image.Image, is_correct_flash: bool = False) -> Image.Image:
    """Creates the answer reveal frame with green neon color."""
    frame = bg_image.copy().resize((WIDTH, HEIGHT), Image.LANCZOS)
    overlay = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    frame = Image.blend(frame, overlay, 0.5)

    draw = ImageDraw.Draw(frame)

    # "ANSWER!" label
    label_font = _get_font(48, bold=True)
    label_text = "✅ ANSWER!"
    bbox = draw.textbbox((0, 0), label_text, font=label_font)
    lx = (WIDTH - (bbox[2] - bbox[0])) // 2
    _draw_text_with_stroke(draw, (lx, HEIGHT // 2 - 160), label_text, label_font,
                           (50, 255, 120), (0, 0, 0), stroke_width=3)

    # Answer text - phosphorescent green
    ans_font = _get_font(72, bold=True)
    lines = _wrap_text(answer_text, max_chars_per_line=20)
    line_height = 85
    start_y = HEIGHT // 2 - 80

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=ans_font)
        text_w = bbox[2] - bbox[0]
        x = (WIDTH - text_w) // 2
        y = start_y + i * line_height
        # Neon green glow effect
        for offset in [(2, 2), (-2, 2), (2, -2), (-2, -2)]:
            draw.text((x + offset[0], y + offset[1]), line, font=ans_font, fill=(0, 180, 80))
        _draw_text_with_stroke(draw, (x, y), line, ans_font, (80, 255, 150), (0, 0, 0), stroke_width=4)

    # Watermark
    wm_font = _get_font(24)
    draw.text((50, HEIGHT - 100), WATERMARK_TEXT, font=wm_font, fill=(200, 200, 200))

    return frame


def compose_short(
    question: str,
    answer: str,
    choices: list,
    template: str,
    bg_video_path: str,
    voice_audio_path: str,
    cta_audio_path: str,
    tick_sfx_path: str,
    ding_sfx_path: str,
    bgm_path: str,
    output_path: str,
) -> str:
    """
    Composes a complete YouTube Short video.
    Structure:
    1. Question display + CTA voiceover (variable length based on audio)
    2. 5-second circular countdown with tick SFX
    3. Answer reveal (1.5-2 seconds) with ding SFX
    Total: ~15-20 seconds (varies per video for anti-spam fingerprinting)
    """
    import subprocess
    import shutil

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    # Randomize answer reveal duration (1.5-2.0 seconds) for variation
    answer_reveal_duration = random.uniform(1.5, 2.0)

    # Get voice audio duration
    def get_audio_duration(path: str) -> float:
        if not path or not os.path.exists(path):
            return 3.0
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
            capture_output=True, text=True
        )
        try:
            data = json.loads(result.stdout)
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "audio":
                    return float(stream.get("duration", 3.0))
        except Exception:
            pass
        return 3.0

    voice_duration = get_audio_duration(voice_audio_path)
    cta_duration = get_audio_duration(cta_audio_path)

    # Phase durations
    question_phase = max(voice_duration + cta_duration + 0.5, 4.0)
    countdown_phase = 5.0
    answer_phase = answer_reveal_duration

    total_duration = question_phase + countdown_phase + answer_phase

    # Apply random micro-variation to total duration (anti-spam)
    duration_variation = random.uniform(-0.3, 0.3)
    total_duration += duration_variation

    total_frames = int(total_duration * FPS)
    countdown_start_frame = int(question_phase * FPS)
    answer_start_frame = countdown_start_frame + int(countdown_phase * FPS)
    countdown_frames = answer_start_frame - countdown_start_frame

    # Timer position: center of top half
    timer_cx = WIDTH - 120
    timer_cy = HEIGHT // 4

    # Load background video/image frames
    bg_frames = _load_background_frames(bg_video_path, total_frames)

    # Build video frames
    frames_dir = tempfile.mkdtemp()

    for i in range(total_frames):
        bg_frame = bg_frames[i % len(bg_frames)]

        if i < countdown_start_frame:
            # Question phase
            frame = _create_question_frame(
                question, choices, template, bg_frame, i,
                countdown_frames, timer_cx, timer_cy
            )
        elif i < answer_start_frame:
            # Countdown phase
            countdown_frame_idx = i - countdown_start_frame
            frame = _create_question_frame(
                question, choices, template, bg_frame,
                countdown_frame_idx, countdown_frames, timer_cx, timer_cy, pop_in_frames=0
            )
        else:
            # Answer phase - no voice, no commentary
            frame = _create_answer_frame(answer, bg_frame)

        frame_path = os.path.join(frames_dir, f"frame_{i:06d}.png")
        frame.save(frame_path, "PNG")

    # Build audio mix
    audio_mix_path = os.path.join(frames_dir, "audio_mix.mp3")
    _build_audio_mix(
        voice_path=voice_audio_path,
        cta_path=cta_audio_path,
        tick_path=tick_sfx_path,
        ding_path=ding_sfx_path,
        bgm_path=bgm_path,
        question_phase=question_phase,
        countdown_phase=countdown_phase,
        answer_phase=answer_phase,
        total_duration=total_duration,
        output_path=audio_mix_path,
    )

    # Encode video with ffmpeg
    frames_pattern = os.path.join(frames_dir, "frame_%06d.png")
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", frames_pattern,
        "-i", audio_mix_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-movflags", "+faststart",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg encoding failed: {result.stderr}")

    # Cleanup temp frames
    shutil.rmtree(frames_dir, ignore_errors=True)
    print(f"[VideoComposer] Short composed: {output_path} ({total_duration:.1f}s)")
    return output_path


def _load_background_frames(bg_video_path: str, num_frames: int) -> list:
    """Loads background frames from video or image."""
    frames = []

    if bg_video_path and os.path.exists(bg_video_path) and bg_video_path.endswith(".mp4"):
        # Extract frames from video using ffmpeg
        tmp_dir = tempfile.mkdtemp()
        cmd = [
            "ffmpeg", "-y",
            "-i", bg_video_path,
            "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}",
            "-frames:v", str(min(num_frames, 300)),  # cap to avoid memory issues
            "-r", str(FPS),
            os.path.join(tmp_dir, "bg_%04d.png")
        ]
        subprocess.run(cmd, capture_output=True)
        for fname in sorted(os.listdir(tmp_dir)):
            if fname.endswith(".png"):
                try:
                    frames.append(Image.open(os.path.join(tmp_dir, fname)).copy())
                except Exception:
                    pass
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not frames:
        # Use image or generate
        if bg_video_path and os.path.exists(bg_video_path):
            try:
                img = Image.open(bg_video_path).resize((WIDTH, HEIGHT), Image.LANCZOS)
                img_blur = img.filter(ImageFilter.GaussianBlur(radius=8))
                frames = [img_blur]
            except Exception:
                pass

    if not frames:
        # Generate gradient fallback
        from asset_fetcher import _generate_gradient_image
        path = _generate_gradient_image()
        img = Image.open(path).resize((WIDTH, HEIGHT), Image.LANCZOS)
        frames = [img]

    return frames


def _build_audio_mix(voice_path, cta_path, tick_path, ding_path, bgm_path,
                     question_phase, countdown_phase, answer_phase, total_duration,
                     output_path):
    """Mixes all audio tracks using ffmpeg filter_complex."""
    inputs = []
    filter_parts = []
    stream_labels = []
    idx = 0

    def add_audio(path, delay_ms, volume=1.0):
        nonlocal idx
        if path and os.path.exists(path):
            inputs += ["-i", path]
            label = f"a{idx}"
            filter_parts.append(f"[{idx}:a]adelay={int(delay_ms)}|{int(delay_ms)},volume={volume}[{label}]")
            stream_labels.append(f"[{label}]")
            idx += 1

    # Voice at start
    add_audio(voice_path, 200, volume=1.0)

    # CTA after voice
    voice_dur = _get_audio_dur_ffprobe(voice_path)
    add_audio(cta_path, int((voice_dur + 0.3) * 1000), volume=0.95)

    # Tick SFX during countdown (every 1 second)
    tick_start_ms = int(question_phase * 1000)
    for tick_sec in range(5):
        add_audio(tick_path, tick_start_ms + tick_sec * 1000, volume=0.7)

    # Ding at answer reveal
    ding_delay_ms = int((question_phase + countdown_phase) * 1000)
    add_audio(ding_path, ding_delay_ms, volume=1.0)

    # BGM throughout (low volume)
    add_audio(bgm_path, 0, volume=0.15)

    if not stream_labels:
        # Silence fallback
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono",
               "-t", str(total_duration), output_path]
        subprocess.run(cmd, capture_output=True)
        return

    import subprocess
    n = len(stream_labels)
    amix_filter = "".join(stream_labels) + f"amix=inputs={n}:duration=first:dropout_transition=2[aout]"
    filter_complex = ";".join(filter_parts) + ";" + amix_filter

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-t", str(total_duration),
        "-ar", "44100",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback: just use voice
        if voice_path and os.path.exists(voice_path):
            subprocess.run(["ffmpeg", "-y", "-i", voice_path, "-t", str(total_duration), output_path],
                           capture_output=True)


def _get_audio_dur_ffprobe(path: str) -> float:
    if not path or not os.path.exists(path):
        return 3.0
    import subprocess, json
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
        capture_output=True, text=True
    )
    try:
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                return float(stream.get("duration", 3.0))
    except Exception:
        pass
    return 3.0


def generate_thumbnail(question: str, template: str, bg_image_path: str, output_path: str) -> str:
    """
    Generates a YouTube thumbnail (1280x720) for long videos.
    """
    thumb_w, thumb_h = 1280, 720
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    if bg_image_path and os.path.exists(bg_image_path):
        try:
            bg = Image.open(bg_image_path).resize((thumb_w, thumb_h), Image.LANCZOS)
        except Exception:
            bg = Image.new("RGB", (thumb_w, thumb_h), (20, 20, 40))
    else:
        bg = Image.new("RGB", (thumb_w, thumb_h), (20, 20, 40))

    # Darken
    dark_overlay = Image.new("RGB", (thumb_w, thumb_h), (0, 0, 0))
    bg = Image.blend(bg, dark_overlay, 0.45)

    draw = ImageDraw.Draw(bg)

    # Channel badge
    badge_font = _get_font(36, bold=True)
    draw.rounded_rectangle([40, 30, 340, 80], radius=8, fill=(255, 50, 50))
    draw.text((55, 38), "🎯 QUIZ PLUS", font=badge_font, fill=(255, 255, 255))

    # Title
    title_font = _get_font(72, bold=True)
    lines = _wrap_text(question[:60] + ("..." if len(question) > 60 else ""), max_chars_per_line=22)
    start_y = 150
    for i, line in enumerate(lines[:3]):
        bbox = draw.textbbox((0, 0), line, font=title_font)
        text_w = bbox[2] - bbox[0]
        x = (thumb_w - text_w) // 2
        _draw_text_with_stroke(draw, (x, start_y + i * 85), line, title_font,
                               (255, 255, 255), (0, 0, 0), stroke_width=4)

    # Template badge at bottom
    t_font = _get_font(44, bold=True)
    badge_text = f"🧠 {template.upper()}"
    draw.rounded_rectangle([40, thumb_h - 90, 520, thumb_h - 30], radius=12, fill=(50, 50, 200))
    draw.text((55, thumb_h - 80), badge_text, font=t_font, fill=(255, 255, 255))

    # "99% FAIL" badge
    fail_font = _get_font(48, bold=True)
    draw.rounded_rectangle([thumb_w - 320, thumb_h - 90, thumb_w - 40, thumb_h - 30],
                           radius=12, fill=(220, 30, 30))
    draw.text((thumb_w - 308, thumb_h - 80), "99% FAIL!", font=fail_font, fill=(255, 255, 255))

    bg.save(output_path, "JPEG", quality=92)
    return output_path
