import os
import cv2
import numpy as np
import random
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional

from core.content_engine import ContentEngine
from core.voice_generator import VoiceGenerator
from core.video_processor import VideoProcessor
from core.thumbnail_generator import ThumbnailGenerator
from core.metadata_optimizer import MetadataOptimizer
from engines.fallback_system import FallbackSystem
from engines.anti_duplicate import AntiDuplicateSystem
from dotenv import load_dotenv

load_dotenv()

class ShortsEngine:
    def __init__(self):
        self.content_engine = ContentEngine()
        self.voice_generator = VoiceGenerator()
        self.video_processor = VideoProcessor()
        self.thumbnail_generator = ThumbnailGenerator()
        self.metadata_optimizer = MetadataOptimizer()
        self.fallback_system = FallbackSystem()
        self.anti_duplicate = AntiDuplicateSystem()
        self.setup_logger()
        self.last_publish_time = None
        self.publish_interval = self._calculate_publish_interval()
        
    def setup_logger(self):
        self.logger = logging.getLogger('ShortsEngine')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('logs/system.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def _calculate_publish_interval(self) -> timedelta:
        """Calculate variable publishing times throughout the day"""
        # Publish 4 shorts per day at varying times
        # Times will be between 8AM-10PM in target audience timezones
        base_hours = [9, 13, 16, 20]  # Base hours for publishing
        variations = [random.randint(-2, 2) for _ in range(4)]  # Random variations
        
        # Ensure times stay within reasonable bounds
        publish_hours = [max(8, min(22, base_hours[i] + variations[i])) for i in range(4)]
        publish_hours.sort()  # Sort to ensure chronological order
        
        # Calculate time differences between publishes
        time_diffs = [
            timedelta(hours=publish_hours[1] - publish_hours[0]),
            timedelta(hours=publish_hours[2] - publish_hours[1]),
            timedelta(hours=publish_hours[3] - publish_hours[2])
        ]
        
        # Return the smallest interval (for scheduling)
        return min(time_diffs)
    
    def generate_short(self) -> Optional[str]:
        """Generate a complete Shorts video with all components"""
        try:
            # 1. Generate question content
            question_data = self.content_engine.generate_question()
            if not question_data:
                self.logger.error("Failed to generate question content")
                return None
                
            self.logger.info(f"Generated question using {question_data['template']} template")
            
            # 2. Generate voice audio
            audio_files = self._generate_audio_components(question_data)
            if not all(audio_files.values()):
                self.logger.error("Failed to generate required audio components")
                return None
                
            # 3. Select background image
            background_path = self.video_processor.select_background()
            if not background_path:
                self.logger.error("Failed to select background image")
                return None
                
            # 4. Create video sequence
            video_path = self._create_video_sequence(question_data, audio_files, background_path)
            if not video_path:
                self.logger.error("Failed to create video sequence")
                return None
                
            # 5. Generate metadata
            metadata = self.metadata_optimizer.generate_metadata(question_data)
            if not metadata:
                self.logger.error("Failed to generate metadata")
                return None
                
            # 6. Generate thumbnail
            thumbnail_path = self.thumbnail_generator.generate_thumbnail(question_data)
            if not thumbnail_path:
                self.logger.error("Failed to generate thumbnail")
                return None
                
            # 7. Finalize and return video path
            self.logger.info(f"Successfully generated Shorts video: {video_path}")
            return video_path
            
        except Exception as e:
            self.logger.error(f"Unexpected error in generate_short: {str(e)}")
            return None
    
    def _generate_audio_components(self, question_data: Dict) -> Dict[str, Optional[str]]:
        """Generate all required audio components for the short"""
        audio_files = {
            "question": None,
            "countdown": None,
            "cta": None
        }
        
        # Generate question audio
        question_audio_path = f"temp/question_{int(time.time())}.mp3"
        if self.voice_generator.generate_audio(question_data["question_text"], question_audio_path):
            audio_files["question"] = question_audio_path
        else:
            self.logger.warning("Falling back to emergency question audio")
            emergency_question = self.content_engine.get_emergency_question(question_data["template"])
            if self.voice_generator.generate_audio(emergency_question["question_text"], question_audio_path):
                audio_files["question"] = question_audio_path
                question_data.update(emergency_question)
        
        # Generate countdown audio
        countdown_audio_path = f"temp/countdown_{int(time.time())}.mp3"
        if self.voice_generator.generate_countdown_audio(countdown_audio_path):
            audio_files["countdown"] = countdown_audio_path
        
        # Generate CTA audio
        cta_text = self.content_engine.generate_cta()
        cta_audio_path = f"temp/cta_{int(time.time())}.mp3"
        if self.voice_generator.generate_audio(cta_text, cta_audio_path):
            audio_files["cta"] = cta_audio_path
        
        return audio_files
    
    def _create_video_sequence(self, question_data: Dict, audio_files: Dict, background_path: str) -> Optional[str]:
        """Create the complete video sequence according to specifications"""
        try:
            # Create output directory if needed
            os.makedirs("output/shorts", exist_ok=True)
            output_path = f"output/shorts/short_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            
            # Process background
            processed_bg = self.video_processor.process_background(background_path)
            
            # Create video sequence with the following structure:
            # 1. Question display with audio (3-4 seconds)
            # 2. CTA display with audio (2 seconds)
            # 3. 5-second countdown
            # 4. Answer display (1-2 seconds)
            # 5. End
            
            # Calculate total duration based on audio lengths
            question_duration = self._get_audio_duration(audio_files["question"])
            cta_duration = self._get_audio_duration(audio_files["cta"])
            countdown_duration = 5.0  # Fixed 5-second countdown
            answer_duration = 1.5     # Fixed answer display time
            
            total_duration = question_duration + cta_duration + countdown_duration + answer_duration
            
            # Create video with correct aspect ratio for Shorts (9:16)
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, 30.0, (1080, 1920))
            
            if not out.isOpened():
                self.logger.error(f"Failed to open video writer for {output_path}")
                return None
            
            # Generate frames for each segment
            self._add_question_segment(out, processed_bg, question_data, question_duration)
            self._add_cta_segment(out, processed_bg, question_data["question_text"], cta_duration)
            self._add_countdown_segment(out, processed_bg, countdown_duration)
            self._add_answer_segment(out, processed_bg, question_data, answer_duration)
            
            # Release the video writer
            out.release()
            
            # Add audio to the video
            if not self.video_processor.add_audio_to_video(output_path, audio_files, total_duration):
                self.logger.warning("Failed to add audio to video, creating silent version")
            
            return output_path
            
        except Exception as e:
            self.logger.error(f"Error creating video sequence: {str(e)}")
            return None
    
    def _get_audio_duration(self, audio_path: str) -> float:
        """Get the duration of an audio file in seconds"""
        if not audio_path or not os.path.exists(audio_path):
            return 2.0  # Default duration
            
        try:
            import wave
            with wave.open(audio_path, 'rb') as audio_file:
                frames = audio_file.getnframes()
                rate = audio_file.getframerate()
                return frames / float(rate)
        except:
            return 2.0  # Default duration
    
    def _add_question_segment(self, out, background, question_data, duration):
        """Add the question display segment to the video"""
        frames = int(duration * 30)  # 30 FPS
        
        for _ in range(frames):
            frame = background.copy()
            
            # Add question text in safe area (centered)
            self._add_text_to_frame(
                frame, 
                question_data["question_text"], 
                position=(540, 960),  # Center of 1080x1920
                font_scale=1.8,
                thickness=3
            )
            
            # Add any template-specific elements
            if question_data["template"] == "multiple_choice" and "options" in question_data:
                y_pos = 1100
                for i, option in enumerate(question_data["options"]):
                    self._add_text_to_frame(
                        frame,
                        f"{chr(65+i)}. {option}",
                        position=(540, y_pos),
                        font_scale=1.4,
                        thickness=2
                    )
                    y_pos += 120
            
            out.write(frame)
    
    def _add_cta_segment(self, out, background, question_text, duration):
        """Add the CTA display segment to the video"""
        frames = int(duration * 30)
        cta_text = self.content_engine.generate_cta()
        
        for _ in range(frames):
            frame = background.copy()
            
            # Add CTA text
            self._add_text_to_frame(
                frame,
                cta_text,
                position=(540, 960),
                font_scale=1.6,
                thickness=3,
                color=(0, 255, 255)  # Distinct color for CTA
            )
            
            # Add a subtle hint of the question
            self._add_text_to_frame(
                frame,
                f"Question: {question_text[:30]}..." if len(question_text) > 30 else f"Question: {question_text}",
                position=(540, 1200),
                font_scale=1.0,
                thickness=2,
                color=(200, 200, 200)
            )
            
            out.write(frame)
    
    def _add_countdown_segment(self, out, background, duration):
        """Add the 5-second countdown segment to the video"""
        total_frames = int(duration * 30)
        countdown_frames = int(5 * 30)  # 5 seconds at 30 FPS
        
        for i in range(countdown_frames):
            frame = background.copy()
            second = 5 - (i // 30)  # Current countdown second
            
            # Draw countdown number
            self._add_text_to_frame(
                frame,
                str(second),
                position=(540, 960),
                font_scale=4.0,
                thickness=5,
                color=(0, 255, 0) if second > 2 else (0, 200, 255) if second > 1 else (0, 0, 255)
            )
            
            # Add progress bar
            progress = i / countdown_frames
            bar_width = int(800 * progress)
            cv2.rectangle(frame, (140, 1300), (140 + bar_width, 1350), (0, 255, 0), -1)
            cv2.rectangle(frame, (140, 1300), (940, 1350), (255, 255, 255), 2)
            
            out.write(frame)
    
    def _add_answer_segment(self, out, background, question_data, duration):
        """Add the answer display segment to the video"""
        frames = int(duration * 30)
        
        for i in range(frames):
            frame = background.copy()
            
            # Only show answer on the last half of the segment
            if i >= frames // 2:
                self._add_text_to_frame(
                    frame,
                    f"ANSWER: {question_data['answer']}",
                    position=(540, 960),
                    font_scale=2.2,
                    thickness=4,
                    color=(0, 255, 0)
                )
                
                # Add explanation if available and on later frames
                if "explanation" in question_data and question_data["explanation"] and i >= frames * 0.7:
                    self._add_text_to_frame(
                        frame,
                        question_data["explanation"],
                        position=(540, 1150),
                        font_scale=1.2,
                        thickness=2,
                        max_width=900
                    )
            
            out.write(frame)
    
    def _add_text_to_frame(self, frame, text, position, font_scale, thickness, color=(255, 255, 255), max_width=None):
        """Add text to a video frame with proper formatting"""
        font = cv2.FONT_HERSHEY_SIMPLEX
        line_type = cv2.LINE_AA
        
        # Calculate text size and wrap if needed
        if max_width:
            wrapped_text = self._wrap_text(text, font, font_scale, max_width, frame.shape[1])
            y = position[1] - ((len(wrapped_text) - 1) * 40) // 2
            
            for line in wrapped_text:
                text_size = cv2.getTextSize(line, font, font_scale, thickness)[0]
                x = max(50, min(position[0] - text_size[0] // 2, frame.shape[1] - text_size[0] - 50))
                cv2.putText(frame, line, (x, y), font, font_scale, color, thickness, line_type)
                y += 50
        else:
            text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
            x = max(50, min(position[0] - text_size[0] // 2, frame.shape[1] - text_size[0] - 50))
            cv2.putText(frame, text, (x, position[1]), font, font_scale, color, thickness, line_type)
    
    def _wrap_text(self, text, font, font_scale, max_width, frame_width):
        """Wrap text to fit within a maximum width"""
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            text_size = cv2.getTextSize(test_line, font, font_scale, 2)[0]
            
            if text_size[0] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
        
        if current_line:
            lines.append(' '.join(current_line))
            
        return lines
    
    def should_publish_now(self) -> bool:
        """Determine if it's time to publish a new Short"""
        now = datetime.now()
        
        # First run always publishes
        if self.last_publish_time is None:
            return True
            
        # Check if enough time has passed since last publish
        time_since_last = now - self.last_publish_time
        
        # Add some randomness to publishing times (±30 minutes)
        target_interval = self.publish_interval + timedelta(minutes=random.randint(-30, 30))
        
        return time_since_last >= target_interval
    
    def publish_short(self, video_path: str):
        """Publish the generated short to YouTube"""
        if not video_path or not os.path.exists(video_path):
            self.logger.error("Cannot publish: video file not found")
            return False
            
        try:
            # Get metadata for this video
            metadata = self.metadata_optimizer.generate_metadata(
                self.content_engine.last_generated_question
            )
            
            # Publish to YouTube
            success = self.video_processor.publish_to_youtube(
                video_path,
                metadata["title"],
                metadata["description"],
                metadata["tags"],
                metadata["thumbnail_path"]
            )
            
            if success:
                self.last_publish_time = datetime.now()
                self.logger.info(f"Successfully published Short: {metadata['title']}")
                return True
            else:
                self.logger.error("Failed to publish Short to YouTube")
                return False
                
        except Exception as e:
            self.logger.error(f"Error during publishing: {str(e)}")
            return False
