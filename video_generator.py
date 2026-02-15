import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import moviepy.editor as mpe
import os
import random
from config import BACKGROUND_DIR
import tempfile

class VideoGenerator:
    def __init__(self):
        self.background_dir = BACKGROUND_DIR
    
    def create_short_video(self, question, answer, background_image_path, audio_path, output_path):
        """Create a YouTube Short video with question and answer"""
        # Create a temporary directory for frames
        with tempfile.TemporaryDirectory() as temp_dir:
            frame_paths = []
            
            # Define video parameters
            width, height = 1080, 1920  # Vertical video for shorts
            fps = 30
            
            # Generate frames for the video
            total_duration = 8  # ~8 seconds: 2s question, 5s timer, 1s answer
            total_frames = total_duration * fps
            
            for i in range(total_frames):
                frame = self._create_frame(
                    question, answer, i, total_frames, 
                    width, height, background_image_path
                )
                
                frame_path = os.path.join(temp_dir, f"frame_{i:05d}.png")
                cv2.imwrite(frame_path, frame)
                frame_paths.append(frame_path)
            
            # Create video from frames
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            video_writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
            
            for frame_path in frame_paths:
                frame = cv2.imread(frame_path)
                video_writer.write(frame)
            
            video_writer.release()
        
        # Add audio to the video
        video_clip = mpe.VideoFileClip(output_path)
        audio_clip = mpe.AudioFileClip(audio_path)
        
        # Set the audio to the video clip
        final_clip = video_clip.set_audio(audio_clip)
        final_clip.write_videofile(output_path, codec='libx264', audio_codec='aac')
        
        return output_path
    
    def _create_frame(self, question, answer, frame_num, total_frames, width, height, bg_path):
        """Create a single frame for the video"""
        # Load background image or create default
        if os.path.exists(bg_path):
            bg = cv2.imread(bg_path)
            bg = cv2.resize(bg, (width, height))
        else:
            # Create a default gradient background
            bg = self._create_gradient_background(width, height)
        
        # Calculate timing phases
        question_duration = int(2 * 30)  # 2 seconds at 30fps
        timer_duration = int(5 * 30)     # 5 seconds at 30fps  
        answer_duration = int(1 * 30)    # 1 second at 30fps
        
        # Determine what to show based on frame number
        if frame_num < question_duration:
            # Show question
            self._draw_text_centered(bg, question, (255, 255, 255), font_size=48)
        elif frame_num < question_duration + timer_duration:
            # Show question + timer countdown
            self._draw_text_centered(bg, question, (255, 255, 255), font_size=48)
            
            # Calculate remaining time for countdown
            elapsed_timer_frames = frame_num - question_duration
            remaining_seconds = max(0, 5 - (elapsed_timer_frames // 30))
            
            # Draw countdown timer
            timer_text = str(remaining_seconds)
            self._draw_text_centered(bg, timer_text, (0, 255, 0), font_size=120, y_offset=200)
        else:
            # Show answer
            self._draw_text_centered(bg, f"Answer: {answer}", (0, 255, 0), font_size=48)
        
        return bg
    
    def _create_gradient_background(self, width, height):
        """Create a gradient background"""
        bg = np.zeros((height, width, 3), dtype=np.uint8)
        
        # Create vertical gradient
        for i in range(height):
            color_value = int(50 + (i / height) * 100)
            bg[i, :] = [color_value // 2, color_value // 2, color_value]
        
        return bg
    
    def _draw_text_centered(self, img, text, color, font_size=48, y_offset=0):
        """Draw centered text on image"""
        h, w = img.shape[:2]
        
        # Use a simple font
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = font_size / 30
        thickness = 2
        
        # Get text size
        text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
        
        # Calculate position to center text
        x = (w - text_size[0]) // 2
        y = (h + text_size[1]) // 2 + y_offset
        
        # Draw text with outline
        cv2.putText(img, text, (x, y), font, font_scale, (0, 0, 0), thickness + 2)
        cv2.putText(img, text, (x, y), font, font_scale, color, thickness)
    
    def select_random_background(self):
        """Select a random background image from the backgrounds directory"""
        if not os.path.exists(self.background_dir):
            os.makedirs(self.background_dir, exist_ok=True)
            return None
        
        images = [f for f in os.listdir(self.background_dir) 
                 if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        
        if images:
            selected = random.choice(images)
            return os.path.join(self.background_dir, selected)
        else:
            return None
