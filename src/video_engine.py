import os
import subprocess
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
import json
from pathlib import Path

logger = logging.getLogger(__name__)

class VideoEngine:
    def __init__(self, output_dir: str = "/tmp/shorts"):
        self.output_dir = output_dir
        self.temp_dir = "/tmp/short_production"
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

    def create_short(self, question_data: Dict[str, Any], audio_params: Dict[str, Any],
                    bg_path: str, music_path: Optional[str], 
                    video_structure: Dict[str, float]) -> Optional[str]:
        """Create complete YouTube Short video"""
        try:
            video_path = self._generate_video_with_ffmpeg(
                question_data, audio_params, bg_path, music_path, video_structure
            )
            
            if video_path:
                logger.info(f"Short created successfully: {video_path}")
                return video_path
            
            return None

        except Exception as e:
            logger.error(f"Error creating short: {e}")
            return None

    def _generate_video_with_ffmpeg(self, question_data: Dict, audio_params: Dict,
                                    bg_path: str, music_path: Optional[str],
                                    structure: Dict[str, float]) -> Optional[str]:
        """Generate video using FFmpeg"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            import io
            
            # Create frames for each segment
            width, height = 1080, 1920
            fps = 30
            
            output_video = os.path.join(
                self.output_dir,
                f"short_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            )
            
            # Create hook frame
            hook_frame = self._create_text_frame(
                width, height,
                question_data['hook'],
                bg_path,
                font_size=60,
                color=(255, 255, 255)
            )
            
            # Create question frame
            question_frame = self._create_text_frame(
                width, height,
                question_data['question'],
                bg_path,
                font_size=45,
                color=(255, 255, 255)
            )
            
            # Create timer frames
            timer_frames = self._create_timer_frames(
                width, height, bg_path,
                duration=structure['timer_duration'],
                fps=fps
            )
            
            # Create answer frame
            answer_frame = self._create_text_frame(
                width, height,
                f"Answer: {question_data['answer']}",
                bg_path,
                font_size=50,
                color=(0, 255, 0)
            )
            
            # Create CTA frame
            cta_frame = self._create_text_frame(
                width, height,
                question_data['cta'],
                bg_path,
                font_size=50,
                color=(255, 200, 0)
            )
            
            # Combine frames using FFmpeg
            concat_cmd = self._build_ffmpeg_concat_command(
                hook_frame, question_frame, timer_frames,
                answer_frame, cta_frame, music_path,
                structure, output_video, fps
            )
            
            result = subprocess.run(concat_cmd, shell=True, 
                                  capture_output=True, text=True)
            
            if result.returncode == 0 and os.path.exists(output_video):
                return output_video
            else:
                logger.error(f"FFmpeg error: {result.stderr}")
                return None

        except Exception as e:
            logger.error(f"Error generating video with FFmpeg: {e}")
            return self._create_fallback_video(question_data, output_video)

    def _create_text_frame(self, width: int, height: int, text: str,
                          bg_path: str, font_size: int = 40,
                          color: tuple = (255, 255, 255)) -> str:
        """Create image frame with text"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            
            # Load or create background
            if bg_path and os.path.exists(bg_path):
                frame = Image.open(bg_path).convert('RGB')
                if frame.size != (width, height):
                    frame = frame.resize((width, height))
            else:
                frame = Image.new('RGB', (width, height), color=(30, 30, 40))
            
            draw = ImageDraw.Draw(frame, 'RGBA')
            
            # Add semi-transparent overlay for better text readability
            overlay = Image.new('RGBA', (width, height), (0, 0, 0, 60))
            frame = Image.alpha_composite(frame.convert('RGBA'), overlay).convert('RGB')
            
            # Draw text
            try:
                # Try to use a nice font, fallback to default
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                                        font_size)
            except:
                font = ImageFont.load_default()
            
            # Word wrap and center text
            lines = self._wrap_text(text, 25)
            total_height = len(lines) * (font_size + 10)
            y_position = (height - total_height) // 2
            
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                text_width = bbox[2] - bbox[0]
                x_position = (width - text_width) // 2
                
                # Add text shadow
                draw.text((x_position + 2, y_position + 2), line,
                        fill=(0, 0, 0, 150), font=font)
                # Add main text
                draw.text((x_position, y_position), line,
                        fill=color + (255,), font=font)
                
                y_position += font_size + 10
            
            # Save frame
            frame_path = os.path.join(self.temp_dir, 
                                     f"frame_{datetime.now().timestamp()}.png")
            frame.save(frame_path)
            
            return frame_path

        except Exception as e:
            logger.error(f"Error creating text frame: {e}")
            return None

    def _wrap_text(self, text: str, width: int = 25) -> List[str]:
        """Wrap text to fit width"""
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            current_line.append(word)
            if len(' '.join(current_line)) > width:
                current_line.pop()
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
        
        if current_line:
            lines.append(' '.join(current_line))
        
        return lines

    def _create_timer_frames(self, width: int, height: int, bg_path: str,
                            duration: float, fps: int) -> List[str]:
        """Create timer countdown frames"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            
            frames = []
            total_frames = int(duration * fps)
            
            for i in range(total_frames):
                time_left = duration - (i / fps)
                
                if bg_path and os.path.exists(bg_path):
                    frame = Image.open(bg_path).convert('RGB')
                    if frame.size != (width, height):
                        frame = frame.resize((width, height))
                else:
                    frame = Image.new('RGB', (width, height), (30, 30, 40))
                
                # Add overlay
                overlay = Image.new('RGBA', (width, height), (0, 0, 0, 60))
                frame = Image.alpha_composite(frame.convert('RGBA'), overlay).convert('RGB')
                
                draw = ImageDraw.Draw(frame, 'RGBA')
                
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 120)
                    timer_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
                except:
                    font = ImageFont.load_default()
                    timer_font = font
                
                # Draw timer
                timer_text = f"{time_left:.1f}"
                bbox = draw.textbbox((0, 0), timer_text, font=timer_font)
                timer_width = bbox[2] - bbox[0]
                timer_height = bbox[3] - bbox[1]
                
                x = (width - timer_width) // 2
                y = (height - timer_height) // 2 + 100
                
                draw.text((x + 3, y + 3), timer_text, fill=(0, 0, 0, 200), font=timer_font)
                draw.text((x, y), timer_text, fill=(255, 100, 100, 255), font=timer_font)
                
                # Draw "Time's Up!" text if time expired
                if time_left <= 0.5:
                    status_text = "Times Up!"
                    bbox = draw.textbbox((0, 0), status_text, font=font)
                    status_width = bbox[2] - bbox[0]
                    sx = (width - status_width) // 2
                    sy = height // 3
                    draw.text((sx, sy), status_text, fill=(255, 0, 0, 255), font=font)
                
                frame_path = os.path.join(self.temp_dir,
                                        f"timer_{i:04d}.png")
                frame.save(frame_path)
                frames.append(frame_path)
            
            return frames

        except Exception as e:
            logger.error(f"Error creating timer frames: {e}")
            return []

    def _build_ffmpeg_concat_command(self, hook_frame: str, question_frame: str,
                                    timer_frames: List[str], answer_frame: str,
                                    cta_frame: str, music_path: Optional[str],
                                    structure: Dict[str, float], output_path: str,
                                    fps: int = 30) -> str:
        """Build FFmpeg command for video composition"""
        try:
            # Create filter graph
            filter_parts = []
            
            # Hook
            hook_duration = structure['hook_duration']
            filter_parts.append(f"[0]scale=1080:1920,fps={fps},trim=0:{hook_duration}[hook]")
            
            # Question
            q_duration = structure['question_display_duration']
            filter_parts.append(
                f"[1]scale=1080:1920,fps={fps},trim=0:{q_duration}[question]"
            )
            
            # Timer
            timer_duration = structure['timer_duration']
            # Create a timer background filter (no trailing semicolon)
            timer_filter = f"color=c=black:s=1080x1920:d={timer_duration}[timer_bg]"
            filter_parts.append(timer_filter)
            
            # Answer
            a_duration = structure['answer_display_duration']
            filter_parts.append(f"[3]scale=1080:1920,fps={fps},trim=0:{a_duration}[answer]")
            
            # CTA
            cta_duration = max(0.5, structure['total_length'] - hook_duration - 
                              q_duration - timer_duration - a_duration)
            filter_parts.append(f"[4]scale=1080:1920,fps={fps},trim=0:{cta_duration}[cta]")
            
            # Concatenate segments
            # Join filter parts and ensure no empty segments
            filter_complex = ";".join(p.rstrip(';') for p in filter_parts if p)
            filter_complex = filter_complex.strip(';')
            filter_complex += f";[hook][question][timer_bg][answer][cta]concat=n=5:v=1[v]"
            
            # Build command
            cmd = f"ffmpeg -y "
            cmd += f"-loop 1 -i '{hook_frame}' "
            cmd += f"-loop 1 -i '{question_frame}' "
            cmd += f"-loop 1 -i '{answer_frame}' "
            cmd += f"-loop 1 -i '{cta_frame}' "
            
            if music_path and os.path.exists(music_path):
                cmd += f"-i '{music_path}' "
                audio_filter = "-filter_complex \"[v]scale=1080:1920[video];[4]aformat=sample_rates=44100[audio]\" -map \"[video]\" -map \"[audio]\" "
            else:
                audio_filter = "-filter_complex \"[v]scale=1080:1920[video]\" -map \"[video]\" "
            
            cmd += f"-f lavfi -i color=c=black:s=1080x1920:d=0.1 "
            cmd += f"-filter_complex \"{filter_complex}\" "
            cmd += audio_filter
            cmd += f"-c:v libx264 -preset veryfast -crf 23 "
            cmd += f"-c:a aac -b:a 128k "
            cmd += f"-shortest "
            cmd += f"'{output_path}'"
            
            return cmd

        except Exception as e:
            logger.error(f"Error building FFmpeg command: {e}")
            return ""

    def _create_fallback_video(self, question_data: Dict, output_path: str) -> Optional[str]:
        """Create simple fallback video if FFmpeg fails"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            
            # Create simple video with moviepy
            width, height = 1080, 1920
            
            # Create single frame with all text
            frame = Image.new('RGB', (width, height), (30, 30, 40))
            draw = ImageDraw.Draw(frame)
            
            try:
                big_font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60
                )
                med_font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 45
                )
            except:
                big_font = med_font = ImageFont.load_default()
            
            # Draw content
            draw.text((100, 200), question_data['hook'],
                     fill=(255, 200, 0), font=big_font)
            draw.text((100, 500), question_data['question'],
                     fill=(255, 255, 255), font=med_font)
            draw.text((100, 1200), f"Answer: {question_data['answer']}",
                     fill=(0, 255, 0), font=med_font)
            draw.text((100, 1600), question_data['cta'],
                     fill=(255, 100, 100), font=med_font)
            
            # Save frame
            frame_path = os.path.join(self.temp_dir, "simple_frame.png")
            frame.save(frame_path)
            
            # Create video using moviepy
            try:
                from moviepy.editor import ImageClip, concatenate_videoclips
                
                clip = ImageClip(frame_path).set_duration(10)
                clip.write_videofile(output_path, fps=30, verbose=False, logger=None)
                
                return output_path if os.path.exists(output_path) else None
            except:
                return None

        except Exception as e:
            logger.error(f"Error creating fallback video: {e}")
            return None

    def add_text_overlay(self, video_path: str, text: str,
                        position: str = "center") -> Optional[str]:
        """Add text overlay to existing video"""
        try:
            output_path = video_path.replace('.mp4', '_overlay.mp4')
            
            x_pos = {"left": "10", "center": "(w-text_w)/2", "right": "w-text_w-10"}
            y_pos = {"top": "10", "center": "(h-text_h)/2", "bottom": "h-text_h-10"}
            
            pos = position.split('_')
            x = x_pos.get(pos[0] if len(pos) > 0 else 'center', "(w-text_w)/2")
            y = y_pos.get(pos[1] if len(pos) > 1 else 'center', "(h-text_h)/2")
            
            cmd = f"""ffmpeg -i '{video_path}' -vf "text=text='{text}':x={x}:y={y}:fontsize=48:fontcolor=white" '{output_path}'"""
            
            result = subprocess.run(cmd, shell=True, capture_output=True)
            
            return output_path if result.returncode == 0 else None

        except Exception as e:
            logger.error(f"Error adding text overlay: {e}")
            return None

    def verify_video_quality(self, video_path: str) -> Dict[str, Any]:
        """Verify video quality and specifications"""
        try:
            cmd = f"""ffprobe -v error -select_streams v:0 -show_entries stream=width,height,duration -of json '{video_path}'"""
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            data = json.loads(result.stdout)
            
            if data.get('streams'):
                stream = data['streams'][0]
                return {
                    'width': stream.get('width'),
                    'height': stream.get('height'),
                    'duration': float(stream.get('duration', 0)),
                    'valid': stream.get('height') == 1920 and stream.get('width') == 1080
                }
            
            return {'valid': False, 'error': 'Unable to read video properties'}

        except Exception as e:
            logger.error(f"Error verifying video: {e}")
            return {'valid': False, 'error': str(e)}

    def cleanup_temp_files(self) -> bool:
        """Clean up temporary files"""
        try:
            import shutil
            
            for file in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            
            return True

        except Exception as e:
            logger.error(f"Error cleaning up temp files: {e}")
            return False
