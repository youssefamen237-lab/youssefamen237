import os
import random
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import textwrap

# Constants for video specifications
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
BACKGROUND_COLOR = (25, 25, 112)  # Midnight Blue
TEXT_COLOR = (255, 255, 0)  # Yellow
TITLE_COLOR = (255, 255, 255)  # White

# Ensure the videos directory exists
os.makedirs('videos', exist_ok=True)


def create_shorts_video(question, answer, cta_text="Like and Subscribe!"):
    """
    Create a YouTube Shorts-style video with the specified question and answer
    Structure:
    - 5 seconds question display
    - 1-2 seconds answer display
    - 5 second countdown
    - CTA
    """
    
    # Create a simple video frame with question
    question_image = create_question_frame(question)
    
    # Create answer frame
    answer_image = create_answer_frame(answer)
    
    # Create CTA frame
    cta_image = create_cta_frame(cta_text)
    
    # Create countdown frames
    countdown_frames = create_countdown_frames()
    
    # For simplicity in this demo, we'll just save the question and answer as separate images
    # In a real implementation, we would use video libraries like moviepy
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Save question image
    question_path = f"videos/question_{timestamp}.png"
    question_image.save(question_path)
    
    # Save answer image
    answer_path = f"videos/answer_{timestamp}.png"
    answer_image.save(answer_path)
    
    # Save CTA image
    cta_path = f"videos/cta_{timestamp}.png"
    cta_image.save(cta_path)
    
    print(f"Created video assets for: {question}")
    return {
        'question_image': question_path,
        'answer_image': answer_path,
        'cta_image': cta_path,
        'timestamp': timestamp
    }


def create_long_video_compilation(questions_and_answers, title="Compilation Video"):
    """
    Create a long-form video compilation from multiple questions and answers
    """
    # In a real implementation, this would compile multiple scenes
    # For now, we'll create a simple compilation frame
    
    # Create a compilation image
    compilation_image = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(compilation_image)
    
    # Load a default font (or handle font loading)
    try:
        font_large = ImageFont.truetype("arial.ttf", 48)
        font_medium = ImageFont.truetype("arial.ttf", 36)
        font_small = ImageFont.truetype("arial.ttf", 24)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()
    
    # Title
    title_text = f"{title}"
    title_bbox = draw.textbbox((0, 0), title_text, font=font_large)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((VIDEO_WIDTH - title_width) // 2, 50), title_text, fill=TITLE_COLOR, font=font_large)
    
    # Add some content
    y_offset = 150
    for i, qa in enumerate(questions_and_answers[:5]):  # Limit to first 5
        question = qa.get('question', f'Question {i+1}')
        answer = qa.get('answer', 'Answer')
        
        # Question
        question_text = f"Q{i+1}: {question}"
        draw.text((50, y_offset), question_text, fill=TEXT_COLOR, font=font_medium)
        y_offset += 60
        
        # Answer
        answer_lines = textwrap.wrap(answer, width=50)
        for line in answer_lines:
            draw.text((70, y_offset), line, fill=(200, 200, 200), font=font_small)
            y_offset += 30
        
        y_offset += 30
        
        if y_offset > VIDEO_HEIGHT - 100:
            break
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = f"videos/compilation_{timestamp}.png"
    compilation_image.save(video_path)
    
    print(f"Created compilation video: {title}")
    return video_path


def create_question_frame(question):
    """Create a frame displaying the question"""
    img = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)
    
    # Load font
    try:
        font_large = ImageFont.truetype("arial.ttf", 60)
        font_medium = ImageFont.truetype("arial.ttf", 40)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
    
    # Wrap question text
    wrapped_question = textwrap.fill(question, width=30)
    
    # Calculate text position
    bbox = draw.textbbox((0, 0), wrapped_question, font=font_large)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (VIDEO_WIDTH - text_width) // 2
    y = (VIDEO_HEIGHT - text_height) // 2
    
    # Draw question text
    draw.text((x, y), wrapped_question, fill=TEXT_COLOR, font=font_large)
    
    return img


def create_answer_frame(answer):
    """Create a frame displaying the answer"""
    img = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)
    
    # Load font
    try:
        font_large = ImageFont.truetype("arial.ttf", 60)
        font_medium = ImageFont.truetype("arial.ttf", 40)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
    
    # Wrap answer text
    wrapped_answer = textwrap.fill(answer, width=30)
    
    # Calculate text position
    bbox = draw.textbbox((0, 0), wrapped_answer, font=font_large)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (VIDEO_WIDTH - text_width) // 2
    y = (VIDEO_HEIGHT - text_height) // 2
    
    # Draw answer text
    draw.text((x, y), wrapped_answer, fill=TEXT_COLOR, font=font_large)
    
    return img


def create_cta_frame(cta_text):
    """Create a frame with call-to-action"""
    img = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)
    
    # Load font
    try:
        font_large = ImageFont.truetype("arial.ttf", 60)
        font_medium = ImageFont.truetype("arial.ttf", 40)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
    
    # Draw CTA text
    bbox = draw.textbbox((0, 0), cta_text, font=font_large)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (VIDEO_WIDTH - text_width) // 2
    y = (VIDEO_HEIGHT - text_height) // 2
    
    draw.text((x, y), cta_text, fill=TEXT_COLOR, font=font_large)
    
    return img


def create_countdown_frames(count=5):
    """Create frames for countdown sequence"""
    frames = []
    for i in range(count, 0, -1):
        img = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), BACKGROUND_COLOR)
        draw = ImageDraw.Draw(img)
        
        try:
            font_large = ImageFont.truetype("arial.ttf", 120)
        except:
            font_large = ImageFont.load_default()
        
        bbox = draw.textbbox((0, 0), str(i), font=font_large)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (VIDEO_WIDTH - text_width) // 2
        y = (VIDEO_HEIGHT - text_height) // 2
        
        draw.text((x, y), str(i), fill=TEXT_COLOR, font=font_large)
        frames.append(img)
    
    return frames


def generate_video_assets(question, answer):
    """Generate all video assets for a single question-answer pair"""
    # Create short video assets
    shorts_assets = create_shorts_video(question, answer)
    
    # Create a longer compilation version
    compilation_assets = create_long_video_compilation([{'question': question, 'answer': answer}])
    
    return {
        'shorts': shorts_assets,
        'compilation': compilation_assets
    }

# Test the video generator
if __name__ == '__main__':
    # Test with sample data
    test_question = "What is the capital of France?"
    test_answer = "Paris is the capital and largest city of France."
    
    assets = generate_video_assets(test_question, test_answer)
    print("Video assets generated successfully:")
    print(f"Shorts assets: {assets['shorts']}\nCompilation: {assets['compilation']}")
