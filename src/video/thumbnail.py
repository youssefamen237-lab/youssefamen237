"""
Thumbnail Generator — creates YouTube thumbnails for Shorts and Long videos.
Uses Pillow for text rendering. Fetches backgrounds from free APIs.
Always generates unique thumbnails — no two are alike.
"""

import os
import random
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance
import requests
import tempfile

THUMBNAILS_DIR = Path("assets/thumbnails")
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)

THUMBNAIL_STYLES = [
    "bold_center",
    "gradient_overlay",
    "dark_dramatic",
    "bright_energetic",
    "split_layout",
    "minimal_clean",
    "neon_glow",
    "fire_effect",
]

COLOR_SCHEMES = [
    {"bg": (10, 10, 30), "accent": (255, 200, 0), "text": (255, 255, 255)},
    {"bg": (20, 0, 40), "accent": (0, 255, 180), "text": (255, 255, 255)},
    {"bg": (30, 0, 0), "accent": (255, 80, 0), "text": (255, 255, 200)},
    {"bg": (0, 20, 40), "accent": (0, 150, 255), "text": (255, 255, 255)},
    {"bg": (0, 30, 10), "accent": (100, 255, 100), "text": (255, 255, 255)},
    {"bg": (40, 0, 40), "accent": (255, 0, 200), "text": (255, 255, 255)},
    {"bg": (30, 20, 0), "accent": (255, 220, 0), "text": (255, 255, 255)},
    {"bg": (0, 0, 50), "accent": (100, 200, 255), "text": (255, 255, 255)},
]

QUESTION_MARK_DESIGNS = ["❓", "?", "🤔", "💡", "🧠", "⚡", "🔥", "✨"]

THUMBNAIL_TEXTS = [
    "Can You Answer?",
    "Only Geniuses Know",
    "Quick Question!",
    "Test Your Knowledge",
    "How Smart Are You?",
    "Challenge Accepted?",
    "Think Fast!",
    "Brain Teaser",
    "Trivia Time!",
    "Do You Know?",
    "Are You Smart Enough?",
    "Quick Quiz!",
]


def get_font(size, bold=False):
    """Try to load a font, fallback to default"""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def add_blur_overlay(img, blur_radius=12, overlay_opacity=160):
    """Apply blur + dark overlay for text readability"""
    blurred = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    overlay = Image.new("RGBA", img.size, (0, 0, 0, overlay_opacity))
    result = blurred.convert("RGBA")
    result.paste(overlay, (0, 0), overlay)
    return result.convert("RGB")


def draw_text_with_shadow(draw, text, pos, font, text_color, shadow_color=(0, 0, 0), shadow_offset=4):
    x, y = pos
    for dx in range(-shadow_offset, shadow_offset + 1):
        for dy in range(-shadow_offset, shadow_offset + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=shadow_color)
    draw.text(pos, text, font=font, fill=text_color)


def draw_text_centered(draw, text, y, img_width, font, text_color, max_width=None, shadow=True):
    if max_width:
        words = text.split()
        lines = []
        current_line = []
        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]
        if current_line:
            lines.append(" ".join(current_line))
    else:
        lines = [text]

    line_height = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        lh = bbox[3] - bbox[1]
        line_height = max(line_height, lh)

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        x = (img_width - w) // 2
        line_y = y + i * (line_height + 10)
        if shadow:
            draw_text_with_shadow(draw, line, (x, line_y), font, text_color)
        else:
            draw.text((x, line_y), line, font=font, fill=text_color)


def create_shorts_thumbnail(question_text, template, background_path=None, output_path=None):
    """Create a 1280x720 thumbnail for YouTube Shorts (displayed as square/portrait)"""
    import time

    if output_path is None:
        output_path = str(THUMBNAILS_DIR / f"thumb_short_{int(time.time())}.jpg")

    width, height = 1280, 720
    scheme = random.choice(COLOR_SCHEMES)
    style = random.choice(THUMBNAIL_STYLES)

    if background_path and os.path.exists(background_path):
        try:
            bg_img = Image.open(background_path).convert("RGB")
            bg_img = bg_img.resize((width, height), Image.LANCZOS)
        except Exception:
            bg_img = Image.new("RGB", (width, height), scheme["bg"])
    else:
        bg_img = Image.new("RGB", (width, height), scheme["bg"])

    img = add_blur_overlay(bg_img, blur_radius=10, overlay_opacity=150)

    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(1.3)

    draw = ImageDraw.Draw(img)

    # Draw accent bar on left
    bar_color = scheme["accent"]
    draw.rectangle([(0, 0), (12, height)], fill=bar_color)
    draw.rectangle([(width - 12, 0), (width, height)], fill=bar_color)

    # Main header text
    header_text = random.choice(THUMBNAIL_TEXTS)
    header_font = get_font(72, bold=True)
    draw_text_centered(draw, header_text, 80, width, header_font, scheme["accent"])

    # Question mark symbol
    symbol = random.choice(QUESTION_MARK_DESIGNS)
    symbol_font = get_font(180, bold=True)
    draw_text_centered(draw, symbol, 200, width, symbol_font, (255, 255, 255))

    # Question preview (shortened)
    short_q = question_text[:60] + ("..." if len(question_text) > 60 else "")
    q_font = get_font(36, bold=True)
    draw_text_centered(draw, short_q, 480, width, q_font, (220, 220, 220), max_width=width - 100)

    # Template badge
    badge_font = get_font(28, bold=True)
    badge_text = f"[ {template.upper()} ]"
    draw_text_centered(draw, badge_text, 640, width, badge_font, scheme["accent"])

    img.save(output_path, "JPEG", quality=95)
    print(f"[Thumbnail] Created: {output_path}")
    return output_path


def create_long_video_thumbnail(title_text, background_path=None, output_path=None):
    """Create a 1280x720 thumbnail for long-form YouTube videos"""
    import time

    if output_path is None:
        output_path = str(THUMBNAILS_DIR / f"thumb_long_{int(time.time())}.jpg")

    width, height = 1280, 720
    scheme = random.choice(COLOR_SCHEMES)

    if background_path and os.path.exists(background_path):
        try:
            bg_img = Image.open(background_path).convert("RGB")
            bg_img = bg_img.resize((width, height), Image.LANCZOS)
        except Exception:
            bg_img = Image.new("RGB", (width, height), scheme["bg"])
    else:
        bg_img = Image.new("RGB", (width, height), scheme["bg"])

    img = add_blur_overlay(bg_img, blur_radius=8, overlay_opacity=130)

    draw = ImageDraw.Draw(img)

    # Top colored strip
    draw.rectangle([(0, 0), (width, 80)], fill=scheme["accent"])

    strip_font = get_font(48, bold=True)
    draw_text_centered(draw, "TRIVIA CHALLENGE", 16, width, strip_font, (0, 0, 0))

    # Giant question mark
    big_q_font = get_font(250, bold=True)
    draw_text_centered(draw, "?", 120, width, big_q_font, (*scheme["accent"], 60))

    # Title text
    title_font = get_font(58, bold=True)
    draw_text_centered(draw, title_text, 200, width, title_font, (255, 255, 255), max_width=width - 140)

    # Sub text
    sub_texts = [
        "How Many Can You Answer?",
        "Test Your Intelligence!",
        "Can You Beat The Challenge?",
        "Ultimate Knowledge Test",
    ]
    sub_font = get_font(36, bold=False)
    draw_text_centered(draw, random.choice(sub_texts), 560, width, sub_font, scheme["accent"])

    # Bottom bar
    draw.rectangle([(0, height - 60), (width, height)], fill=scheme["accent"])
    bottom_font = get_font(30, bold=True)
    draw_text_centered(draw, "SUBSCRIBE FOR DAILY CHALLENGES", height - 50, width, bottom_font, (0, 0, 0))

    img.save(output_path, "JPEG", quality=95)
    print(f"[Thumbnail] Long video created: {output_path}")
    return output_path


if __name__ == "__main__":
    t = create_shorts_thumbnail("What is the capital of Australia?", "Direct Question")
    print(f"Thumbnail: {t}")
