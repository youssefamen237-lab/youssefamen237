"""
Long Video Renderer — creates 5+ minute compilation videos from multiple questions.
Each question gets: intro segment, question display, timer, answer reveal.
All assembled with FFmpeg inside GitHub Actions runner.
"""

import os
import json
import random
import subprocess
import tempfile
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

OUTPUT_DIR = Path("output/long")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FPS = 30

INTRO_DURATION = 5    # seconds
QUESTION_DURATION = 4  # seconds per question (before timer)
TIMER_DURATION = 5     # seconds
ANSWER_DURATION = 3    # seconds
TRANSITION_DURATION = 1  # seconds between questions

MIN_QUESTIONS = 15  # ensures 5+ minutes

COLOR_PRESETS = [
    {"bg": (10, 10, 30), "accent": (255, 200, 0), "text": (255, 255, 255), "secondary": (200, 200, 255)},
    {"bg": (20, 0, 50), "accent": (0, 255, 200), "text": (255, 255, 255), "secondary": (150, 255, 230)},
    {"bg": (30, 5, 5), "accent": (255, 80, 0), "text": (255, 240, 200), "secondary": (255, 180, 100)},
]

LONG_VIDEO_TITLES_TEMPLATES = [
    "Can You Answer ALL {n} Questions?",
    "{n} Trivia Questions — How Many Can You Get?",
    "Ultimate {n}-Question Knowledge Challenge",
    "The {n}-Question Genius Test",
    "{n} Questions That Will Test Your Brain",
    "How Smart Are You? {n} Questions!",
    "{n} Brain-Busting Trivia Questions",
    "Master Quiz: {n} Questions You Must Answer",
]


def get_font(size, bold=True):
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_centered_text(draw, text, y, img_width, font, color, max_width=None, shadow=True):
    if max_width:
        words = text.split()
        lines = []
        current = []
        for word in words:
            test = " ".join(current + [word])
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current.append(word)
            else:
                if current:
                    lines.append(" ".join(current))
                current = [word]
        if current:
            lines.append(" ".join(current))
    else:
        lines = [text]

    lh_list = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        lh_list.append(bbox[3] - bbox[1])

    for i, (line, lh) in enumerate(zip(lines, lh_list)):
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        x = (img_width - w) // 2
        line_y = y + i * (lh + 12)
        if shadow:
            for dx in [-3, 0, 3]:
                for dy in [-3, 0, 3]:
                    if dx or dy:
                        draw.text((x + dx, line_y + dy), line, font=font, fill=(0, 0, 0))
        draw.text((x, line_y), line, font=font, fill=color)


def create_intro_frame(title, total_questions, color_preset, channel_name="QuizBrain"):
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), color_preset["bg"])
    draw = ImageDraw.Draw(img)

    # Background gradient effect
    for y in range(VIDEO_HEIGHT):
        ratio = y / VIDEO_HEIGHT
        r = int(color_preset["bg"][0] + (30 - color_preset["bg"][0]) * ratio)
        g = int(color_preset["bg"][1] + (10 - color_preset["bg"][1]) * ratio)
        b = int(color_preset["bg"][2] + (50 - color_preset["bg"][2]) * ratio)
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(r, g, b))

    # Channel name
    ch_font = get_font(55)
    draw_centered_text(draw, channel_name.upper(), 80, VIDEO_WIDTH, ch_font, color_preset["accent"])

    # Decorative lines
    accent = color_preset["accent"]
    draw.rectangle([(0, 140), (VIDEO_WIDTH, 148)], fill=accent)
    draw.rectangle([(0, VIDEO_HEIGHT - 148), (VIDEO_WIDTH, VIDEO_HEIGHT - 140)], fill=accent)

    # Title
    title_font = get_font(85)
    draw_centered_text(draw, title, 250, VIDEO_WIDTH, title_font, color_preset["text"], max_width=VIDEO_WIDTH - 200)

    # Question count badge
    badge_font = get_font(60)
    badge_text = f"⚡ {total_questions} QUESTIONS ⚡"
    draw_centered_text(draw, badge_text, 580, VIDEO_WIDTH, badge_font, color_preset["accent"])

    # Subscribe CTA
    sub_font = get_font(42)
    draw_centered_text(draw, "Subscribe for daily trivia challenges!", 780, VIDEO_WIDTH, sub_font, (200, 200, 200))
    draw_centered_text(draw, "Hit the notification bell to never miss a quiz!", 840, VIDEO_WIDTH, sub_font, (180, 180, 180))

    # Bottom instruction
    inst_font = get_font(38)
    draw_centered_text(draw, "Comment how many you get right!", 950, VIDEO_WIDTH, inst_font, color_preset["secondary"])

    return img


def create_question_separator_frame(question_number, total, color_preset):
    """Frame between questions showing question number"""
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), color_preset["bg"])
    draw = ImageDraw.Draw(img)

    # Simple gradient
    for y in range(VIDEO_HEIGHT):
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=tuple(max(0, c - int(c * 0.3 * y / VIDEO_HEIGHT)) for c in color_preset["bg"]))

    # Question number
    num_font = get_font(200)
    num_text = f"#{question_number}"
    draw_centered_text(draw, num_text, 280, VIDEO_WIDTH, num_font, color_preset["accent"])

    # Progress bar
    progress = question_number / total
    bar_x = 150
    bar_y = VIDEO_HEIGHT - 100
    bar_width = VIDEO_WIDTH - 300
    bar_height = 20
    draw.rectangle([(bar_x, bar_y), (bar_x + bar_width, bar_y + bar_height)], fill=(50, 50, 50))
    draw.rectangle([(bar_x, bar_y), (bar_x + int(bar_width * progress), bar_y + bar_height)], fill=color_preset["accent"])

    return img


def create_question_frame_16_9(question_text, template, color_preset):
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), color_preset["bg"])
    draw = ImageDraw.Draw(img)

    # Background
    for y in range(VIDEO_HEIGHT):
        ratio = y / VIDEO_HEIGHT
        r = int(color_preset["bg"][0] * (1 - ratio * 0.3))
        g = int(color_preset["bg"][1] * (1 - ratio * 0.3))
        b = int(color_preset["bg"][2] + (80 - color_preset["bg"][2]) * ratio * 0.4)
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(max(0, r), max(0, g), min(255, b)))

    # Template label
    label_font = get_font(45)
    draw_centered_text(draw, f"◆ {template.upper()} ◆", 50, VIDEO_WIDTH, label_font, color_preset["accent"])

    # Question card
    margin = 80
    card_top = 180
    card_bottom = VIDEO_HEIGHT - 150
    draw.rounded_rectangle([margin, card_top, VIDEO_WIDTH - margin, card_bottom], radius=25, fill=(0, 0, 0, 180) if False else (15, 15, 35), outline=color_preset["accent"], width=4)

    q_font = get_font(62)
    draw_centered_text(draw, question_text, (card_top + card_bottom) // 2 - 60, VIDEO_WIDTH, q_font, color_preset["text"], max_width=VIDEO_WIDTH - 250)

    return img


def create_timer_frame_16_9(seconds_left, color_preset):
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), color_preset["bg"])
    draw = ImageDraw.Draw(img)

    for y in range(VIDEO_HEIGHT):
        ratio = y / VIDEO_HEIGHT
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(int(color_preset["bg"][0] * (1 + ratio * 0.5)), int(color_preset["bg"][1] * (1 + ratio * 0.3)), int(color_preset["bg"][2] * (1 + ratio * 0.2))))

    # Huge timer number
    timer_font = get_font(400)
    num_text = str(seconds_left)
    bbox = draw.textbbox((0, 0), num_text, font=timer_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (VIDEO_WIDTH - tw) // 2
    ty = (VIDEO_HEIGHT - th) // 2 - 50

    # Glow effect
    for offset in [20, 15, 10, 5]:
        alpha = 30
        for dx in range(-offset, offset + 1, offset):
            for dy in range(-offset, offset + 1, offset):
                draw.text((tx + dx, ty + dy), num_text, font=timer_font, fill=(*color_preset["accent"][:3],))

    draw.text((tx, ty), num_text, font=timer_font, fill=color_preset["accent"])

    # "SECONDS" label
    sec_font = get_font(55)
    draw_centered_text(draw, "SECONDS TO ANSWER", VIDEO_HEIGHT - 120, VIDEO_WIDTH, sec_font, (200, 200, 200))

    return img


def create_answer_frame_16_9(question_text, answer_text, color_preset):
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (5, 5, 20))
    draw = ImageDraw.Draw(img)

    # Answer banner
    draw.rectangle([(0, 0), (VIDEO_WIDTH, 120)], fill=color_preset["accent"])
    banner_font = get_font(65)
    bbox = draw.textbbox((0, 0), "✓ THE ANSWER IS:", font=banner_font)
    bw = bbox[2] - bbox[0]
    draw.text(((VIDEO_WIDTH - bw) // 2, 25), "✓ THE ANSWER IS:", font=banner_font, fill=(0, 0, 0))

    # Answer card
    draw.rounded_rectangle([100, 180, VIDEO_WIDTH - 100, VIDEO_HEIGHT - 180], radius=30, fill=(15, 15, 40), outline=color_preset["accent"], width=8)

    ans_font = get_font(100)
    draw_centered_text(draw, answer_text, (VIDEO_HEIGHT - 100) // 2, VIDEO_WIDTH, ans_font, color_preset["accent"], max_width=VIDEO_WIDTH - 280)

    # Question repeat (small)
    q_font = get_font(38)
    draw_centered_text(draw, f'Q: {question_text[:80]}{"..." if len(question_text) > 80 else ""}', VIDEO_HEIGHT - 160, VIDEO_WIDTH, q_font, (160, 160, 160), max_width=VIDEO_WIDTH - 200)

    return img


def render_long_video(questions_list, title, output_path=None):
    """
    Render a 5+ minute long-form compilation video.
    questions_list: list of dicts with question/answer/template
    """
    if output_path is None:
        output_path = str(OUTPUT_DIR / f"long_{int(time.time())}.mp4")

    color_preset = random.choice(COLOR_PRESETS)
    n = len(questions_list)

    tmp_dir = tempfile.mkdtemp()
    frames_dir = os.path.join(tmp_dir, "frames")
    os.makedirs(frames_dir)

    frame_num = 0

    def save_frames(frame_img, count):
        nonlocal frame_num
        for _ in range(count):
            frame_img.save(os.path.join(frames_dir, f"frame_{frame_num:06d}.jpg"), "JPEG", quality=88)
            frame_num += 1

    print(f"[LongVideo] Rendering intro...")
    intro_frame = create_intro_frame(title, n, color_preset)
    save_frames(intro_frame, INTRO_DURATION * FPS)

    for idx, q in enumerate(questions_list, start=1):
        print(f"[LongVideo] Question {idx}/{n}: {q['question'][:50]}")

        # Separator frame (1s)
        sep = create_question_separator_frame(idx, n, color_preset)
        save_frames(sep, 1 * FPS)

        # Question display
        q_frame = create_question_frame_16_9(q["question"], q.get("template", "Trivia"), color_preset)
        save_frames(q_frame, QUESTION_DURATION * FPS)

        # Timer countdown 5→1
        for sec in [5, 4, 3, 2, 1]:
            t_frame = create_timer_frame_16_9(sec, color_preset)
            save_frames(t_frame, 1 * FPS)

        # Answer reveal
        a_frame = create_answer_frame_16_9(q["question"], q["answer"], color_preset)
        save_frames(a_frame, ANSWER_DURATION * FPS)

    # Outro frame
    outro_img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), color_preset["bg"])
    outro_draw = ImageDraw.Draw(outro_img)
    outro_font = get_font(90)
    draw_centered_text(outro_draw, "SUBSCRIBE", 300, VIDEO_WIDTH, outro_font, color_preset["accent"])
    draw_centered_text(outro_draw, "for daily trivia challenges!", 430, VIDEO_WIDTH, get_font(55), color_preset["text"])
    draw_centered_text(outro_draw, "Comment your score below! 🏆", 560, VIDEO_WIDTH, get_font(50), (200, 200, 200))
    save_frames(outro_img, 5 * FPS)

    total_frames = frame_num
    duration_seconds = total_frames / FPS
    print(f"[LongVideo] Total frames: {total_frames} ({duration_seconds:.1f}s = {duration_seconds/60:.1f}min)")

    # Render video with FFmpeg
    print("[LongVideo] Running FFmpeg...")
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", os.path.join(frames_dir, "frame_%06d.jpg"),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}",
        output_path,
    ]
    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg long video failed: {result.stderr[:500]}")

    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"[LongVideo] Done: {output_path} ({size_mb:.1f} MB, {duration_seconds:.0f}s)")
    return output_path


def generate_long_video_title(n):
    template = random.choice(LONG_VIDEO_TITLES_TEMPLATES)
    return template.format(n=n)


if __name__ == "__main__":
    test_questions = [
        {"question": f"Test question {i}?", "answer": f"Answer {i}", "template": "Direct Question"}
        for i in range(1, 16)
    ]
    title = generate_long_video_title(len(test_questions))
    path = render_long_video(test_questions, title, "/tmp/test_long.mp4")
    print(f"Long video: {path}")
