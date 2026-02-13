import os
import random
import json
import hashlib
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta
import logging
from enum import Enum

logger = logging.getLogger(__name__)

# Workspace base directory
BASE_DIR = os.getenv('GITHUB_WORKSPACE') or os.getcwd()

class QuestionType(Enum):
    TRUE_FALSE = "True/False"
    MULTIPLE_CHOICE = "Multiple Choice"
    VISUAL_DIFFERENCE = "Visual Difference"
    QUICK_SOLVE = "Quick Solve"
    GUESS_ANSWER = "Guess the Answer"
    GENIUS_ONLY = "Only Geniuses Can Solve"
    FIVE_SECOND = "5 Second Challenge"
    MEMORY_TEST = "Memory Test"
    TRIVIA = "Trivia"
    BRAIN_TEASER = "Brain Teaser"
    OPTICAL_ILLUSION = "Optical Illusion"
    QUICK_MATH = "Quick Math"
    POP_CULTURE = "Pop Culture"

class ContentGenerator:
    def __init__(self, db_manager):
        self.db = db_manager
        self.question_types = [t.value for t in QuestionType]
        self.cta_variations = [
            "Write your answer below",
            "Drop it in the comments",
            "Think fast",
            "Can you solve it?",
            "Comment your answer",
            "What's your answer?",
            "Let me know below",
            "Challenge yourself",
            "Comment now",
            "Quick answer below",
            "Your turn to guess",
            "Try to solve it",
            "Can you answer this?",
            "Share your answer",
            "Show off your brain"
        ]
        
        self.hooks = [
            "Only 1% Can Solve This",
            "This Will Break Your Brain",
            "Can You Figure It Out?",
            "Challenge: Solve in 5 Seconds",
            "Not Everyone Can Get This Right",
            "Brain Teaser Alert",
            "Quick Test",
            "Are You Smart Enough?",
            "Impossible Challenge",
            "99% Fail This",
            "Ultimate Brain Test",
            "Can You Beat This?",
            "Genius Level Challenge",
            "Mind-Bending",
            "Tricky Question"
        ]
        
        self.trivia_questions = {
            QuestionType.TRUE_FALSE.value: [
                {"q": "The Great Wall of China is visible from space", "a": "False"},
                {"q": "Honey never spoils", "a": "True"},
                {"q": "Venus is the hottest planet", "a": "True"},
                {"q": "Dolphins are fish", "a": "False"},
                {"q": "A group of flamingos is called a flamboyance", "a": "True"},
                {"q": "Octopuses have 3 hearts", "a": "True"},
                {"q": "Sloths can run up to 30 mph", "a": "False"},
                {"q": "A day on Venus is longer than its year", "a": "True"},
                {"q": "Mountain goats have rectangular pupils", "a": "True"},
                {"q": "Penguins have knees", "a": "True"},
            ],
            QuestionType.QUICK_MATH.value: [
                {"q": "What is 47 + 53?", "a": "100"},
                {"q": "What is 12 × 8?", "a": "96"},
                {"q": "What is 144 ÷ 12?", "a": "12"},
                {"q": "What is 2^8?", "a": "256"},
                {"q": "What is 15% of 200?", "a": "30"},
                {"q": "What is √256?", "a": "16"},
                {"q": "What is 7 × 9 - 3?", "a": "60"},
                {"q": "What is 100 - 37 + 12?", "a": "75"},
            ],
            QuestionType.TRIVIA.value: [
                {"q": "Which planet is closest to the Sun?", "a": "Mercury"},
                {"q": "Who painted the Mona Lisa?", "a": "Leonardo da Vinci"},
                {"q": "What is the capital of Japan?", "a": "Tokyo"},
                {"q": "How many continents are there?", "a": "7"},
                {"q": "Who invented the light bulb?", "a": "Thomas Edison"},
                {"q": "What is the largest ocean?", "a": "Pacific Ocean"},
                {"q": "Which country has the most population?", "a": "India"},
                {"q": "What is the largest mammal?", "a": "Blue Whale"},
            ],
            QuestionType.BRAIN_TEASER.value: [
                {"q": "If you have a bowl of 3 apples and take 2, how many do you have?", "a": "2"},
                {"q": "What has hands but cannot clap?", "a": "Clock"},
                {"q": "I speak without a mouth. What am I?", "a": "Echo"},
                {"q": "The more you take, the more you leave behind. What am I?", "a": "Footsteps"},
            ],
            QuestionType.MEMORY_TEST.value: [
                {"q": "Sequence: 2, 4, 6, 8, ?", "a": "10"},
                {"q": "Sequence: 1, 1, 2, 3, 5, ?", "a": "8"},
                {"q": "Sequence: A, C, E, G, ?", "a": "I"},
            ],
            QuestionType.OPTICAL_ILLUSION.value: [
                {"q": "Which line is longer?", "a": "They're equal"},
                {"q": "How many faces do you see?", "a": "Depends on perception"},
            ],
            QuestionType.POP_CULTURE.value: [
                {"q": "In which year did Avatar release?", "a": "2009"},
                {"q": "Who is known as the King of Pop?", "a": "Michael Jackson"},
                {"q": "What does MCU stand for?", "a": "Marvel Cinematic Universe"},
            ]
        }

    def should_create_new_content(self) -> bool:
        """Check if enough time has passed and content is unique"""
        try:
            # Check database for recent content
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''SELECT COUNT(*) as count FROM upload_history 
                           WHERE upload_timestamp > datetime('now', '-1 day')''')
            today_uploads = cursor.fetchone()['count']
            conn.close()

            return today_uploads < 8  # Max 4-8 per day

        except Exception as e:
            logger.error(f"Error checking content frequency: {e}")
            return True

    def generate_question(self) -> Optional[Dict[str, Any]]:
        """Generate unique question content"""
        try:
            max_attempts = 5
            for attempt in range(max_attempts):
                question_type = random.choice(self.question_types)
                
                if question_type not in self.trivia_questions:
                    continue
                
                questions = self.trivia_questions[question_type]
                if not questions:
                    continue
                
                question_data = random.choice(questions)
                question_text = question_data['q']

                # Check for recent duplicates
                if self.db.check_content_similarity(question_text, threshold=0.75):
                    continue

                return {
                    'type': question_type,
                    'question': question_text,
                    'answer': question_data['a'],
                    'hook': random.choice(self.hooks),
                    'cta': random.choice(self.cta_variations),
                    'generated_at': datetime.now().isoformat()
                }

            logger.warning("Could not generate unique content after max attempts")
            return None

        except Exception as e:
            logger.error(f"Error generating question: {e}")
            return None

    def get_audio_parameters(self) -> Dict[str, Any]:
        """Get current audio preferences based on strategy"""
        try:
            strategy = self.db.get_strategy_analysis()
            
            # Get voice gender preference (weighted)
            voice_preferences = strategy.get('voice_gender_performance', {})
            
            # Default preferences
            voice_gender = "female" if random.random() > 0.4 else "male"
            speech_speed = random.uniform(0.95, 1.05)
            
            if voice_preferences:
                if 'female' in voice_preferences and voice_preferences['female']['avg_score'] > 0.5:
                    voice_gender = "female" if random.random() > 0.3 else "male"
                elif 'male' in voice_preferences:
                    voice_gender = "male" if random.random() > 0.3 else "female"
            
            return {
                'voice_gender': voice_gender,
                'speech_speed': round(speech_speed, 2),
                'pitch': random.uniform(0.9, 1.1),
                'tone': random.choice(['neutral', 'excited', 'calm']),
                'volume': 0.85
            }

        except Exception as e:
            logger.error(f"Error getting audio parameters: {e}")
            return {
                'voice_gender': 'female',
                'speech_speed': 1.0,
                'pitch': 1.0,
                'tone': 'neutral',
                'volume': 0.85
            }

    def get_video_structure(self) -> Dict[str, Any]:
        """Get current video structure parameters"""
        try:
            strategy = self.db.get_strategy_analysis()
            
            return {
                'hook_duration': 0.7,
                'question_display_duration': random.uniform(0.5, 1.0),
                'timer_duration': random.uniform(4.8, 5.3),
                'answer_display_duration': random.uniform(1.0, 2.0),
                'total_length': random.uniform(8.5, 15.5)
            }

        except Exception as e:
            logger.error(f"Error getting video structure: {e}")
            return {
                'hook_duration': 0.7,
                'question_display_duration': 0.7,
                'timer_duration': 5.0,
                'answer_display_duration': 1.5,
                'total_length': 9.0
            }

    def select_background(self) -> Optional[str]:
        """Select background intelligently"""
        try:
            bg_dir = os.path.join(BASE_DIR, 'assets', 'backgrounds')
            
            if os.path.exists(bg_dir):
                backgrounds = [f for f in os.listdir(bg_dir) 
                              if f.endswith(('.mp4', '.png', '.jpg'))]
                
                if backgrounds:
                    # Prefer least recently used
                    least_used = self.db.get_least_used_backgrounds(limit=5)
                    candidates = [f for f in least_used if f in backgrounds]
                    
                    if candidates:
                        selected = candidates[0]
                    else:
                        selected = random.choice(backgrounds)
                    
                    return os.path.join(bg_dir, selected)
            
            # Generate gradient background if none available
            return self._generate_gradient_background()

        except Exception as e:
            logger.error(f"Error selecting background: {e}")
            return self._generate_gradient_background()

    def _generate_gradient_background(self) -> str:
        """Generate random gradient background"""
        try:
            from PIL import Image
            
            width, height = 1080, 1920
            gradient = Image.new('RGB', (width, height))
            pixels = gradient.load()
            
            color1 = tuple(random.randint(20, 100) for _ in range(3))
            color2 = tuple(random.randint(100, 200) for _ in range(3))
            
            for y in range(height):
                for x in range(width):
                    ratio = y / height
                    r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
                    g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
                    b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
                    pixels[x, y] = (r, g, b)
            
            bg_path = "/tmp/generated_gradient.png"
            gradient.save(bg_path)
            return bg_path

        except Exception as e:
            logger.error(f"Error generating gradient background: {e}")
            return None

    def select_music(self) -> Optional[str]:
        """Select music intelligently"""
        try:
            music_dir = os.path.join(BASE_DIR, 'assets', 'music')
            
            if os.path.exists(music_dir):
                music_files = [f for f in os.listdir(music_dir) 
                              if f.endswith(('.mp3', '.wav', '.m4a'))]
                
                if music_files:
                    # Check usage frequency
                    available_music = []
                    for music_file in music_files:
                        metadata = self.db.get_music_metadata(music_file)
                        usage = metadata['usage_count'] if metadata else 0
                        
                        if usage < 3 or not metadata:
                            available_music.append((music_file, usage))
                    
                    if available_music:
                        available_music.sort(key=lambda x: x[1])
                        selected = available_music[0][0]
                        return os.path.join(music_dir, selected)
                    
                    return os.path.join(music_dir, random.choice(music_files))
            
            return None

        except Exception as e:
            logger.error(f"Error selecting music: {e}")
            return None

    def generate_title(self, question_type: str, attempt: int = 0) -> str:
        """Generate SEO-optimized title"""
        title_templates = [
            "Only 1% Can Solve This {type} Challenge",
            "Can You Answer This {type} Question?",
            "Brain Teaser: {type}",
            "{type} - Can You Solve It?",
            "Quick {type} Challenge - Shorts",
            "Ultimate {type} Test",
            "99% Fail This {type}",
            "Genius Level {type}",
            "{type} Quiz - 5 Second Challenge",
            "Mind-Bending {type} Question"
        ]
        
        template = random.choice(title_templates)
        title = template.format(type=question_type)
        
        # Add variety to titles
        if attempt == 0:
            return title[:60]
        else:
            return f"{title} [Part {attempt + 1}]"[:60]

    def generate_description(self, question_type: str, cta: str) -> str:
        """Generate description with SEO optimization"""
        descriptions = [
            f"{cta}!\nCan you solve this {question_type}? Challenge your brain with our daily brain teasers!\n#shorts #quiz #brainiacks",
            f"Test your knowledge with this {question_type}!\n{cta}. Don't forget to like and subscribe!\n#shorts #viral #challenge",
            f"Quick {question_type} quiz for you!\n{cta} - How fast can you solve it?\n#shorts #quiz #brainteaser",
        ]
        
        return random.choice(descriptions)

    def generate_hashtags(self, question_type: str, count: int = 15) -> List[str]:
        """Generate relevant hashtags"""
        general_tags = [
            "#Shorts", "#Quiz", "#BrainTeaser", "#Challenge",
            "#Viral", "#BrainIQ", "#Memory", "#Fast",
            "#Trivia", "#Smart", "#Think", "#Logic"
        ]
        
        type_specific = {
            "Trivia": ["#Trivia", "#Knowledge", "#Fun"],
            "Brain Teaser": ["#BrainTeaser", "#Logic", "#Think"],
            "Quick Math": ["#Math", "#Numbers", "#Calculate"],
            "Memory Test": ["#Memory", "#Brain", "#Focus"],
            "Optical Illusion": ["#Illusion", "#Visual", "#Perception"],
        }
        
        tags = general_tags.copy()
        if question_type in type_specific:
            tags.extend(type_specific[question_type])
        
        return random.sample(tags, min(count, len(tags)))

    def get_content_metadata(self, question_data: Dict, audio_params: Dict, 
                            bg_path: str, music_path: Optional[str]) -> Dict[str, str]:
        """Calculate content hashes for DNA tracking"""
        try:
            question_hash = hashlib.sha256(
                question_data['question'].encode()
            ).hexdigest()
            
            audio_hash = hashlib.sha256(
                json.dumps(audio_params, sort_keys=True).encode()
            ).hexdigest()
            
            bg_hash = hashlib.sha256(
                (bg_path or "").encode()
            ).hexdigest()
            
            music_hash = hashlib.sha256(
                (music_path or "").encode()
            ).hexdigest()
            
            return {
                'hash_question': question_hash,
                'hash_audio': audio_hash,
                'hash_background': bg_hash,
                'hash_music': music_hash,
                'content_type': question_data['type']
            }

        except Exception as e:
            logger.error(f"Error calculating content metadata: {e}")
            return {}
