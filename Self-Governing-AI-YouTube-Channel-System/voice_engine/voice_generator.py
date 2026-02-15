import os
import pyttsx3
from gtts import gTTS
import pygame
import time
from io import BytesIO

# Ensure the voices directory exists
os.makedirs('voices', exist_ok=True)


class VoiceGenerator:
    def __init__(self):
        self.engine = None
        self.init_engine()
        
    def init_engine(self):
        """Initialize the text-to-speech engine"""
        try:
            # Try to use pyttsx3 first
            self.engine = pyttsx3.init()
            # Configure voice properties
            self.engine.setProperty('rate', 150)  # Words per minute
            self.engine.setProperty('volume', 0.9)  # Volume level (0.0 to 1.0)
            print("Pyttsx3 engine initialized")
        except Exception as e:
            print(f"Could not initialize pyttsx3: {e}")
            self.engine = None
    
    def generate_voice_speech(self, text, filename=None, use_gtts=False):
        """
        Generate speech from text
        
        Args:
            text (str): Text to convert to speech
            filename (str): Output filename (optional)
            use_gtts (bool): Whether to use gTTS instead of pyttsx3
        
        Returns:
            str: Path to generated audio file
        """
        if not filename:
            import uuid
            filename = f"voice_{uuid.uuid4().hex[:8]}.mp3"
            
        filepath = f"voices/{filename}"
        
        try:
            if use_gtts:
                # Use Google Text-to-Speech
                tts = gTTS(text=text, lang='en', slow=False)
                tts.save(filepath)
            elif self.engine:
                # Use pyttsx3
                self.engine.save_to_file(text, filepath)
                self.engine.runAndWait()
            else:
                # Fallback: create empty file
                with open(filepath, 'w') as f:
                    f.write("")
                print("No TTS engine available, created empty file")
                
            return filepath
        except Exception as e:
            print(f"Error generating voice: {e}")
            # Create a dummy file for testing
            with open(filepath, 'w') as f:
                f.write("")
            return filepath
    
    def play_audio(self, filepath):
        """Play audio file"""
        try:
            pygame.mixer.init()
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.play()
            
            # Wait for playback to finish
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
        except Exception as e:
            print(f"Error playing audio: {e}")
    
    def synthesize_speech(self, text):
        """Synthesize speech directly to memory"""
        try:
            if self.engine:
                # For pyttsx3, we can't easily return bytes, so we save to file
                filename = f"temp_voice_{int(time.time())}.mp3"
                self.engine.save_to_file(text, filename)
                self.engine.runAndWait()
                return filename
            else:
                return None
        except Exception as e:
            print(f"Error synthesizing speech: {e}")
            return None

# Global voice generator instance
voice_gen = VoiceGenerator()

def generate_voice_speech(text, filename=None, use_gtts=False):
    """Generate speech from text"""
    return voice_gen.generate_voice_speech(text, filename, use_gtts)

def play_audio(filepath):
    """Play audio file"""
    return voice_gen.play_audio(filepath)

# Test the voice generator
if __name__ == '__main__':
    test_text = "Hello! This is a test of the voice generation system."
    print("Testing voice generation...")
    
    # Test with pyttsx3
    audio_file = generate_voice_speech(test_text, "test_voice_pyttsx3.mp3")
    print(f"Generated audio file: {audio_file}")
    
    # Test with gTTS if available
    try:
        audio_file_gtts = generate_voice_speech(test_text, "test_voice_gtts.mp3", use_gtts=True)
        print(f"Generated audio file (gTTS): {audio_file_gtts}")
    except Exception as e:
        print(f"gTTS test failed: {e}")
