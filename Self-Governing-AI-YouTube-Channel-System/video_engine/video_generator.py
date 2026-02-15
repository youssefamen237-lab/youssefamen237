import moviepy.editor as mp
from PIL import Image, ImageDraw, ImageFont
from . import question_generator

# Define a function to generate a video
def generate_video(question, answer):
    # Set the video duration
    duration = 10  # seconds
    
    # Set the video resolution
    width, height = 1080, 1920
    
    # Create a clip for the question
    question_clip = mp.ImageClip('background.png').set_duration(duration)
    
    # Add text to the question clip
    question_image = Image.new('RGB', (width, height), color = (73, 109, 137))
    question_draw = ImageDraw.Draw(question_image)
    question_font = ImageFont.load_default()
    question_draw.text((width/2, height/2), question, font=question_font, fill=(255, 255, 0))
    question_clip = mp.ImageClip(question_image).set_duration(duration)
    
    # Create a clip for the answer
    answer_clip = mp.ImageClip('background.png').set_duration(2)
    
    # Add text to the answer clip
    answer_image = Image.new('RGB', (width, height), color = (73, 109, 137))
    answer_draw = ImageDraw.Draw(answer_image)
    answer_font = ImageFont.load_default()
    answer_draw.text((width/2, height/2), answer, font=answer_font, fill=(255, 255, 0))
    answer_clip = mp.ImageClip(answer_image).set_duration(2)
    
    # Concatenate the clips
    video = mp.concatenate_videoclips([question_clip, answer_clip])
    
    # Write the video to a file
    video.write_videofile('video.mp4', fps=24)

    return video
