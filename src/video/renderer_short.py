"""
Short Video Renderer — assembles complete YouTube Shorts using FFmpeg.
Structure: Question display → Timer (5s) → Answer reveal (1-2s)
All video assembled natively in GitHub Actions runner using FFmpeg.
"""

import os
import json
import random
import subprocess
import tempfile
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance
import numpy as np

OUTPUT_DIR = Path("output/shorts")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# YouTube Shorts: 1080x1920 vertical 9:16
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30
BACKGROUND_BLUR_RADIUS = 18

FONT_SIZES = {
    "template_label": 40,
    "question": 65,
    "answer": 80,
    "timer": 150,
    "cta": 38,
}

COLOR_PRESETS = [
    {"overlay": (10, 10, 30, 200), "accent": (255, 200, 0), "text": (255, 255, 255), "timer": (255, 100, 0)},
    {"overlay": (20, 0, 50, 190), "accent": (0, 255, 200), "text": (255, 255, 255), "timer": (0, 200, 255)},
    {"overlay": (30, 0, 0, 195), "accent": (255, 80, 0), "text": (255, 240, 200), "timer": (255, 180, 0)},
    {"overlay": (0, 20, 50, 200), "accent": (100, 180, 255), "text": (255, 255, 255), "timer": (0, 200, 255)},
    {"overlay": (0, 30, 10, 190), "accent": (100, 255, 120), "text": (255, 255, 255), "timer": (0, 255, 150)},
]


def get_font(size, bold=True):
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def prepare_background(bg_path):
    """Resize, blur and darken background for safe zone"""
    if bg_path and os.path.exists(bg_path):
        img = Image.open(bg_path).convert("RGB")
    else:
        img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (10, 10, 30))

    # Resize to fill 1080x1920
    target_ratio = VIDEO_WIDTH / VIDEO_HEIGHT
    img_ratio = img.width / img.height
    if img_ratio > target_ratio:
        new_height = VIDEO_HEIGHT
        new_width = int(new_height * img_ratio)
    else:
        new_width = VIDEO_WIDTH
        new_height = int(new_width / img_ratio)

    img = img.resize((new_width, new_height), Image.LANCZOS)
    left = (new_width - VIDEO_WIDTH) // 2
    top = (new_height - VIDEO_HEIGHT) // 2
    img = img.crop((left, top, left + VIDEO_WIDTH, top + VIDEO_HEIGHT))

    img = img.filter(ImageFilter.GaussianBlur(radius=BACKGROUND_BLUR_RADIUS))
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(0.45)
    return img


def draw_text_wrapped_centered(draw, text, center_y, img_width, font, color, max_width, line_spacing=15):
    """Draw multi-line centered text with auto-wrap"""
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))

    line_heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_heights.append(bbox[3] - bbox[1])

    total_height = sum(line_heights) + line_spacing * (len(lines) - 1)
    start_y = center_y - total_height // 2

    for i, (line, lh) in enumerate(zip(lines, line_heights)):
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        x = (img_width - w) // 2
        y = start_y + sum(line_heights[:i]) + line_spacing * i

        # Shadow
        for dx in [-3, 0, 3]:
            for dy in [-3, 0, 3]:
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=color)


def draw_rounded_rect(draw, xy, radius, fill, outline=None, outline_width=3):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill, outline=outline, width=outline_width)


def create_question_frame(bg_img, question_text, template_label, cta_text, color_preset, frame_number=0):
    """Create a single frame showing the question"""
    img = bg_img.copy().convert("RGBA")
    overlay = Image.new("RGBA", img.size, color_preset["overlay"])
    img = Image.alpha_composite(img, overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    safe_left = 60
    safe_right = VIDEO_WIDTH - 60
    safe_width = safe_right - safe_left

    # Template label at top
    label_font = get_font(FONT_SIZES["template_label"])
    label_text = f"◆ {template_label.upper()} ◆"
    bbox = draw.textbbox((0, 0), label_text, font=label_font)
    lw = bbox[2] - bbox[0]
    lh = bbox[3] - bbox[1]
    lx = (VIDEO_WIDTH - lw) // 2
    ly = 220
    draw_rounded_rect(draw, (lx - 20, ly - 12, lx + lw + 20, ly + lh + 12), 15, (0, 0, 0, 120))
    draw.text((lx, ly), label_text, font=label_font, fill=color_preset["accent"])

    # Question card background
    card_top = 400
    card_bottom = 1200
    card_margin = 50
    draw_rounded_rect(
        draw,
        (card_margin, card_top, VIDEO_WIDTH - card_margin, card_bottom),
        30,
        (0, 0, 0, 160),
        outline=color_preset["accent"],
        outline_width=4,
    )

    # Question text
    q_font = get_font(FONT_SIZES["question"])
    draw_text_wrapped_centered(
        draw,
        question_text,
        center_y=(card_top + card_bottom) // 2,
        img_width=VIDEO_WIDTH,
        font=q_font,
        color=color_preset["text"],
        max_width=safe_width - 40,
        line_spacing=20,
    )

    # CTA text below card
    cta_font = get_font(FONT_SIZES["cta"])
    draw_text_wrapped_centered(
        draw,
        cta_text,
        center_y=1380,
        img_width=VIDEO_WIDTH,
        font=cta_font,
        color=(200, 200, 200),
        max_width=safe_width,
    )

    # Pulse animation on border (slight opacity change by frame)
    if frame_number % 15 < 8:
        pulse_color = (*color_preset["accent"], 80)
        glow_overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_overlay)
        glow_draw.rounded_rectangle(
            (card_margin - 8, card_top - 8, VIDEO_WIDTH - card_margin + 8, card_bottom + 8),
            radius=36,
            outline=(*color_preset["accent"], 40),
            width=12,
        )
        img = img.convert("RGBA")
        img = Image.alpha_composite(img, glow_overlay).convert("RGB")

    return img


def create_timer_frame(bg_img, question_text, seconds_left, color_preset):
    """Create a timer countdown frame"""
    img = bg_img.copy().convert("RGBA")
    overlay = Image.new("RGBA", img.size, color_preset["overlay"])
    img = Image.alpha_composite(img, overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    safe_width = VIDEO_WIDTH - 120

    # Question still visible (smaller)
    q_font = get_font(50)
    card_margin = 50
    draw_rounded_rect(
        draw,
        (card_margin, 250, VIDEO_WIDTH - card_margin, 820),
        25,
        (0, 0, 0, 150),
        outline=color_preset["accent"],
        outline_width=3,
    )
    draw_text_wrapped_centered(
        draw,
        question_text,
        center_y=530,
        img_width=VIDEO_WIDTH,
        font=q_font,
        color=color_preset["text"],
        max_width=safe_width - 40,
    )

    # Timer circle
    timer_cx, timer_cy = VIDEO_WIDTH // 2, 1200
    timer_radius = 220

    # Outer glow
    glow_overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_overlay)
    timer_color = color_preset["timer"]
    glow_alpha = 60 + int(40 * abs(seconds_left - 2.5) / 2.5)
    glow_draw.ellipse(
        (timer_cx - timer_radius - 20, timer_cy - timer_radius - 20,
         timer_cx + timer_radius + 20, timer_cy + timer_radius + 20),
        fill=(*timer_color, glow_alpha),
    )
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, glow_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Timer background circle
    draw.ellipse(
        (timer_cx - timer_radius, timer_cy - timer_radius,
         timer_cx + timer_radius, timer_cy + timer_radius),
        fill=(0, 0, 0, 180) if isinstance((0,0,0,180), tuple) else (0, 0, 0),
        outline=timer_color,
        width=12,
    )
    # Actually draw solid circle
    draw.ellipse(
        (timer_cx - timer_radius, timer_cy - timer_radius,
         timer_cx + timer_radius, timer_cy + timer_radius),
        fill=(15, 15, 35),
        outline=timer_color,
        width=12,
    )

    # Timer number
    timer_font = get_font(FONT_SIZES["timer"])
    num_text = str(seconds_left) if isinstance(seconds_left, int) else f"{seconds_left:.1f}"
    num_text = str(int(seconds_left) + 1) if seconds_left == int(seconds_left) else str(int(seconds_left) + 1)
    # Use the integer countdown value
    display_num = str(seconds_left)
    bbox = draw.textbbox((0, 0), display_num, font=timer_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = timer_cx - tw // 2
    ty = timer_cy - th // 2
    # Shadow
    for dx in [-4, 0, 4]:
        for dy in [-4, 0, 4]:
            if dx != 0 or dy != 0:
                draw.text((tx + dx, ty + dy), display_num, font=timer_font, fill=(0, 0, 0))
    draw.text((tx, ty), display_num, font=timer_font, fill=timer_color)

    # "seconds" label
    sec_font = get_font(45)
    sec_text = "SECONDS LEFT"
    bbox = draw.textbbox((0, 0), sec_text, font=sec_font)
    sw = bbox[2] - bbox[0]
    draw.text(((VIDEO_WIDTH - sw) // 2, timer_cy + timer_radius + 30), sec_text, font=sec_font, fill=(180, 180, 180))

    return img


def create_answer_frame(bg_img, question_text, answer_text, color_preset):
    """Create the answer reveal frame"""
    img = bg_img.copy().convert("RGBA")
    overlay = Image.new("RGBA", img.size, (*color_preset["overlay"][:3], 210))
    img = Image.alpha_composite(img, overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # "ANSWER" header
    header_font = get_font(60)
    header_text = "✓ ANSWER"
    header_color = color_preset["accent"]
    bbox = draw.textbbox((0, 0), header_text, font=header_font)
    hw = bbox[2] - bbox[0]
    draw.text(((VIDEO_WIDTH - hw) // 2, 350), header_text, font=header_font, fill=header_color)

    # Answer card
    card_margin = 60
    draw_rounded_rect(
        draw,
        (card_margin, 500, VIDEO_WIDTH - card_margin, 1100),
        35,
        (0, 0, 0),
        outline=color_preset["accent"],
        outline_width=6,
    )

    # Answer text
    ans_font = get_font(FONT_SIZES["answer"])
    draw_text_wrapped_centered(
        draw,
        answer_text,
        center_y=800,
        img_width=VIDEO_WIDTH,
        font=ans_font,
        color=color_preset["accent"],
        max_width=VIDEO_WIDTH - 180,
    )

    return img


def render_short_video(question_data, background_path, output_path=None):
    """
    Render a complete YouTube Short video.
    Returns path to the final MP4 file.
    """
    if output_path is None:
        output_path = str(OUTPUT_DIR / f"short_{int(time.time())}.mp4")

    color_preset = random.choice(COLOR_PRESETS)
    bg_img = prepare_background(background_path)

    tmp_dir = tempfile.mkdtemp()
    frames_dir = os.path.join(tmp_dir, "frames")
    os.makedirs(frames_dir)

    question_text = question_data["question"]
    answer_text = question_data["answer"]
    template = question_data.get("template", "Direct Question")
    cta_text = question_data.get("cta", "Drop your answer in the comments!")

    frame_num = 0

    # SECTION 1: Question display — 3 seconds (90 frames)
    print("[Video] Rendering question frames...")
    for i in range(90):
        frame = create_question_frame(bg_img, question_text, template, cta_text, color_preset, frame_number=i)
        frame.save(os.path.join(frames_dir, f"frame_{frame_num:05d}.jpg"), "JPEG", quality=90)
        frame_num += 1

    # SECTION 2: Timer countdown — 5 seconds (150 frames)
    print("[Video] Rendering timer frames...")
    for sec in [5, 4, 3, 2, 1]:
        for i in range(30):  # 30 frames per second
            frame = create_timer_frame(bg_img, question_text, sec, color_preset)
            frame.save(os.path.join(frames_dir, f"frame_{frame_num:05d}.jpg"), "JPEG", quality=90)
            frame_num += 1

    # SECTION 3: Answer reveal — 1.5 seconds (45 frames)
    print("[Video] Rendering answer frames...")
    for i in range(45):
        frame = create_answer_frame(bg_img, question_text, answer_text, color_preset)
        frame.save(os.path.join(frames_dir, f"frame_{frame_num:05d}.jpg"), "JPEG", quality=90)
        frame_num += 1

    total_frames = frame_num
    print(f"[Video] Total frames rendered: {total_frames}")

    # ── Step: Render silent video from frames ─────────────────────
    silent_mp4 = os.path.join(tmp_dir, "silent.mp4")
    ffmpeg_video = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", os.path.join(frames_dir, "frame_%05d.jpg"),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}",
        silent_mp4
    ]
    result = subprocess.run(ffmpeg_video, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"[Video] FFmpeg video render failed: {result.stderr[:300]}")
    print(f"[Video] Silent video rendered: {os.path.getsize(silent_mp4)//1024}KB")

    # ── Step: Merge audio into video ──────────────────────────────
    combined_audio = question_data.get("combined_audio")
    audio_question  = question_data.get("audio_question")

    audio_file = None
    if combined_audio and os.path.exists(combined_audio) and os.path.getsize(combined_audio) > 1000:
        audio_file = combined_audio
        print(f"[Video] Using combined audio track: {os.path.getsize(audio_file)//1024}KB")
    elif audio_question and os.path.exists(audio_question) and os.path.getsize(audio_question) > 1000:
        audio_file = audio_question
        print(f"[Video] Using question-only audio: {os.path.getsize(audio_file)//1024}KB")

    if audio_file:
        merge_cmd = [
            "ffmpeg", "-y",
            "-i", silent_mp4,
            "-i", audio_file,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-ar", "44100",
            "-map", "0:v:0", "-map", "1:a:0",
            # Audio plays from start; video is longer (countdown + answer) so pad audio with silence
            "-af", "apad",
            "-shortest",
            output_path
        ]
        merge_result = subprocess.run(merge_cmd, capture_output=True, text=True)
        if merge_result.returncode != 0:
            print(f"[Video] Audio merge failed: {merge_result.stderr[:200]}")
            print("[Video] Falling back to video-only (checking if audio path issue)...")
            # Try with explicit re-encode
            merge_cmd2 = [
                "ffmpeg", "-y",
                "-i", silent_mp4,
                "-i", audio_file,
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-map", "0:v", "-map", "1:a",
                "-af", "apad",
                "-shortest",
                output_path
            ]
            merge_result2 = subprocess.run(merge_cmd2, capture_output=True, text=True)
            if merge_result2.returncode != 0:
                print(f"[Video] Second merge attempt failed: {merge_result2.stderr[:200]}")
                import shutil
                shutil.copy(silent_mp4, output_path)
            else:
                print("[Video] ✓ Audio merged on second attempt")
        else:
            print("[Video] ✓ Audio merged successfully")
    else:
        import shutil
        print("[Video] ⚠ No audio file available — video will be silent")
        shutil.copy(silent_mp4, output_path)

    # Cleanup temp files
    import shutil as _shutil
    _shutil.rmtree(tmp_dir, ignore_errors=True)

    file_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"[Video] Short complete: {output_path} ({file_size:.1f} MB)")
    return output_path


if __name__ == "__main__":
    test_q = {
        "question": "What is the capital of Australia?",
        "answer": "Canberra",
        "template": "Direct Question",
        "cta": "Drop your answer in the comments before time runs out!",
    }
    path = render_short_video(test_q, None, "/tmp/test_short.mp4")
    print(f"Video: {path}")
