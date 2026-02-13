import os
import logging
from typing import Dict, List, Optional, Any, Tuple
import json
import re

logger = logging.getLogger(__name__)

class ContentSafetyChecker:
    """Check content for safety and compliance"""
    
    BANNED_WORDS = [
        'death', 'kill', 'murder', 'suicide',
        'war', 'attack', 'bomb', 'terrorism',
        'politics', 'political', 'democrat', 'republican',
        'sexual', 'sex', 'explicit',
        'religion', 'atheist', 'christian', 'muslim', 'jewish',
        'racist', 'hate', 'discrimination'
    ]
    
    SENSITIVE_TOPICS = [
        'politics', 'elections', 'government',
        'religion', 'faith', 'beliefs',
        'violence', 'crime', 'murder',
        'sexual content', 'pornography',
        'drug abuse', 'substance'
    ]
    
    def __init__(self):
        self.gemini_api_key = os.getenv('GEMINI_API_KEY')
        self.openai_api_key = os.getenv('OPENAI_API_KEY')

    def check_content_safety(self, question_text: str, answer_text: str,
                           title: str, description: str) -> Tuple[bool, str]:
        """Check content for unsafe material"""
        try:
            # Basic word filter
            combined_text = f"{question_text} {answer_text} {title} {description}".lower()
            
            for banned_word in self.BANNED_WORDS:
                if banned_word in combined_text:
                    return False, f"Contains banned word: {banned_word}"
            
            # Check for suspiciously sensitive topics
            for topic in self.SENSITIVE_TOPICS:
                if topic in combined_text:
                    logger.warning(f"Content contains sensitive topic: {topic}")
                    # Don't reject, just warn
            
            # Check with Gemini if available
            if self.gemini_api_key:
                is_safe_gemini, reason_gemini = self._check_with_gemini(
                    question_text, answer_text
                )
                if not is_safe_gemini:
                    return False, f"Gemini flagged: {reason_gemini}"
            
            # Check with OpenAI if available
            if self.openai_api_key:
                is_safe_openai, reason_openai = self._check_with_openai(
                    question_text, answer_text
                )
                if not is_safe_openai:
                    return False, f"OpenAI flagged: {reason_openai}"
            
            return True, "Content is safe"

        except Exception as e:
            logger.error(f"Error checking content safety: {e}")
            # Assume safe if check fails
            return True, "Safety check error - allowing content"

    def _check_with_gemini(self, question_text: str, answer_text: str) -> Tuple[bool, str]:
        """Check with Google Gemini API"""
        try:
            import google.generativeai as genai
            
            genai.configure(api_key=self.gemini_api_key)
            model = genai.GenerativeModel('gemini-pro')
            
            prompt = f"""Check if this content is appropriate for YouTube monetization.
            
Question: {question_text}
Answer: {answer_text}

Reply with YES or NO, and a brief reason."""
            
            response = model.generate_content(prompt)
            text = response.text.lower()
            
            is_safe = 'yes' in text
            reason = text[:100]
            
            return is_safe, reason

        except Exception as e:
            logger.warning(f"Gemini check failed: {e}")
            return True, "Check skipped"

    def _check_with_openai(self, question_text: str, answer_text: str) -> Tuple[bool, str]:
        """Check with OpenAI Moderation API"""
        try:
            import openai
            
            openai.api_key = self.openai_api_key
            
            moderation_input = f"{question_text} {answer_text}"
            
            response = openai.Moderation.create(input=moderation_input)
            
            results = response['results'][0]
            
            is_safe = not results['flagged']
            categories = [cat for cat, flagged in results['category_scores'].items() 
                         if results[cat]]
            reason = f"Flagged categories: {', '.join(categories)}"
            
            return is_safe, reason

        except Exception as e:
            logger.warning(f"OpenAI check failed: {e}")
            return True, "Check skipped"


class AudioValidator:
    """Validate and process audio content"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        self.eleven_labs_key = os.getenv('ELEVEN_API_KEY')
        self.groq_key = os.getenv('GROQ_API_KEY')
        self.assembly_ai_key = os.getenv('ASSEMBLYAI')

    def generate_voiceover(self, text: str, voice_gender: str = 'female',
                          speech_speed: float = 1.0) -> Optional[str]:
        """Generate voiceover for text"""
        try:
            if self.eleven_labs_key:
                return self._generate_with_elevenlabs(text, voice_gender, speech_speed)
            else:
                return self._generate_with_gtts(text, voice_gender, speech_speed)

        except Exception as e:
            logger.error(f"Error generating voiceover: {e}")
            return None

    def _generate_with_elevenlabs(self, text: str, voice_gender: str,
                                 speech_speed: float) -> Optional[str]:
        """Generate speech with Eleven Labs"""
        try:
            import requests
            
            # Map voice IDs based on gender preference
            voice_ids = {
                'male': ['Adam', 'Antoni', 'Arnold'],
                'female': ['Bella', 'Clara', 'Domi']
            }
            
            voice_id = voice_ids.get(voice_gender, voice_ids['female'])[0]
            
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {
                "xi-api-key": self.eleven_labs_key,
                "Content-Type": "application/json"
            }
            
            payload = {
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75
                }
            }
            
            response = requests.post(url, json=payload, headers=headers)
            
            if response.status_code == 200:
                audio_path = f"/tmp/voiceover_{int(time.time())}.mp3"
                with open(audio_path, 'wb') as f:
                    f.write(response.content)
                return audio_path
            
            logger.warning(f"ElevenLabs API error: {response.status_code}")
            return None

        except Exception as e:
            logger.error(f"Error with ElevenLabs: {e}")
            return None

    def _generate_with_gtts(self, text: str, voice_gender: str,
                           speech_speed: float) -> Optional[str]:
        """Fallback to Google Text-to-Speech"""
        try:
            from gtts import gTTS
            import time
            
            # Use English accent
            lang = 'en'
            
            tts = gTTS(text=text, lang=lang, slow=speech_speed < 1.0)
            
            audio_path = f"/tmp/voiceover_{int(time.time())}.mp3"
            tts.save(audio_path)
            
            return audio_path

        except Exception as e:
            logger.error(f"Error with gTTS: {e}")
            return None

    def analyze_audio_quality(self, audio_path: str) -> Dict[str, Any]:
        """Analyze audio quality"""
        try:
            import librosa
            import numpy as np
            
            if not os.path.exists(audio_path):
                return {'error': 'File not found'}
            
            # Load audio
            y, sr = librosa.load(audio_path)
            
            # Calculate metrics
            duration = librosa.get_duration(y=y, sr=sr)
            
            # Energy
            S = librosa.feature.melspectrogram(y=y, sr=sr)
            energy = np.mean(librosa.power_to_db(S, ref=np.max))
            
            # Zero crossing rate
            zcr = np.mean(librosa.feature.zero_crossing_rate(y))
            
            # Spectral centroid
            spectral_centroid = np.mean(librosa.feature.spectral_centroid(y=y, sr=sr))
            
            return {
                'duration': round(duration, 2),
                'energy': round(energy, 2),
                'zero_crossing_rate': round(zcr, 4),
                'spectral_centroid': round(spectral_centroid, 2),
                'quality_score': self._rate_quality(energy, zcr),
                'valid': duration > 1 and duration < 20
            }

        except Exception as e:
            logger.error(f"Error analyzing audio: {e}")
            return {'valid': False, 'error': str(e)}

    def _rate_quality(self, energy: float, zcr: float) -> float:
        """Rate audio quality (0-1)"""
        # Simple metric based on energy levels
        if -40 < energy < -10:
            quality = 0.9
        elif -50 < energy < 0:
            quality = 0.7
        else:
            quality = 0.5
        
        return quality


class ContentOptimizer:
    """Optimize content for maximum engagement"""
    
    def __init__(self, db_manager):
        self.db = db_manager

    def optimize_title(self, title: str, question_type: str) -> str:
        """Optimize title for CTR"""
        optimizations = {
            'Trivia': lambda t: f"Can You Answer This {question_type}? 🧠",
            'Brain Teaser': lambda t: f"GENIUS-ONLY {question_type}! 🔥",
            'Quick Math': lambda t: f"Solve in 5 Seconds! {question_type} ⏱️",
            'Memory Test': lambda t: f"Ultimate {question_type} Challenge! 💭",
            'Optical Illusion': lambda t: f"What Do YOU See? {question_type}! 👀",
            'True/False': lambda t: f"Fact or Fiction? {question_type}! 🤔"
        }
        
        if question_type in optimizations:
            return optimizations[question_type](title)
        
        return title[:60]

    def optimize_description(self, base_description: str, 
                           question_type: str, tags: List[str]) -> str:
        """Optimize description for SEO"""
        hashtags = " ".join(["#" + tag.replace(" ", "") for tag in tags[:10]])
        
        optimized = f"""{base_description}

📌 Did you get it right? Drop your answer below!

{hashtags}

👉 Subscribe for more brain teasers & quizzes!
"""
        
        return optimized

    def optimize_cta(self, base_cta: str, attempt_number: int = 0) -> str:
        """Optimize call-to-action"""
        cta_variations = [
            f"{base_cta} 👇",
            f"Comment: {base_cta.lower()} 💬",
            f"Your turn! {base_cta}",
            f"Challenge me! {base_cta}",
            f"Can you? {base_cta} ⏰"
        ]
        
        if attempt_number < len(cta_variations):
            return cta_variations[attempt_number]
        
        import random
        return random.choice(cta_variations)

    def analyze_engagement_drivers(self) -> Dict[str, Any]:
        """Analyze what drives engagement"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Top performing CTAs
            cursor.execute('''SELECT cta_used, AVG(performance_score) as avg_score, COUNT(*) as count
                           FROM video_performance
                           WHERE cta_used IS NOT NULL
                           GROUP BY cta_used
                           ORDER BY avg_score DESC
                           LIMIT 5''')
            
            top_ctas = cursor.fetchall()
            
            # Top performing question types
            cursor.execute('''SELECT question_type, AVG(performance_score) as avg_score, COUNT(*) as count
                           FROM video_performance
                           GROUP BY question_type
                           ORDER BY avg_score DESC''')
            
            top_types = cursor.fetchall()
            
            # Best times to post
            cursor.execute('''SELECT strftime('%H', upload_time) as hour, 
                           AVG(performance_score) as avg_score, COUNT(*) as count
                         FROM video_performance
                         GROUP BY hour
                         ORDER BY avg_score DESC
                         LIMIT 3''')
            
            best_hours = cursor.fetchall()
            
            conn.close()
            
            return {
                'top_ctas': [dict(row) for row in top_ctas],
                'top_question_types': [dict(row) for row in top_types],
                'best_posting_hours': [dict(row) for row in best_hours]
            }

        except Exception as e:
            logger.error(f"Error analyzing engagement drivers: {e}")
            return {}


class TrendInjector:
    """Inject trending topics into content"""
    
    def __init__(self):
        self.serpapi_key = os.getenv('SERPAPI')
        self.tavily_key = os.getenv('TAVILY_API_KEY')
        self.news_api_key = os.getenv('NEWS_API')

    def get_trending_topics(self, regions: List[str] = None) -> List[str]:
        """Get trending topics"""
        if regions is None:
            regions = ['us', 'uk', 'ca', 'au']
        
        trends = []
        
        for region in regions:
            try:
                trends.extend(self._get_google_trends(region))
                trends.extend(self._get_news_trends(region))
            except Exception as e:
                logger.warning(f"Error getting trends for {region}: {e}")
        
        return list(set(trends))[:20]

    def _get_google_trends(self, region: str) -> List[str]:
        """Get Google Trends"""
        try:
            import requests
            
            if not self.serpapi_key:
                return []
            
            url = "https://serpapi.com/search"
            params = {
                "q": "trending",
                "tbm": "nws",
                "tbs": "qdr:d",
                "gl": region,
                "api_key": self.serpapi_key
            }
            
            response = requests.get(url, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                trends = [item['title'] for item in data.get('news', [])[:10]]
                return trends
            
            return []

        except Exception as e:
            logger.warning(f"Error getting Google trends: {e}")
            return []

    def _get_news_trends(self, region: str) -> List[str]:
        """Get news-based trends"""
        try:
            import requests
            
            if not self.news_api_key:
                return []
            
            url = "https://newsapi.org/v2/top-headlines"
            params = {
                "country": region[:2],
                "apiKey": self.news_api_key,
                "pageSize": 5
            }
            
            response = requests.get(url, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                trends = [article['title'] for article in data.get('articles', [])]
                return trends
            
            return []

        except Exception as e:
            logger.warning(f"Error getting news trends: {e}")
            return []

    def create_trend_based_content(self, trend: str) -> Optional[Dict[str, str]]:
        """Create content based on trending topic"""
        try:
            # Create trivia question from trend
            prompt = f"""Create a simple trivia question based on this trend: {trend}
            
Format:
Question: [safe, engaging question about the trend]
Answer: [correct answer]"""
            
            # Use available LLM APIs
            if os.getenv('OPENAI_API_KEY'):
                return self._create_with_openai(prompt)
            elif os.getenv('GROQ_API_KEY'):
                return self._create_with_groq(prompt)
            else:
                return None

        except Exception as e:
            logger.error(f"Error creating trend content: {e}")
            return None

    def _create_with_openai(self, prompt: str) -> Optional[Dict[str, str]]:
        """Create content with OpenAI"""
        try:
            import openai
            openai.api_key = os.getenv('OPENAI_API_KEY')
            
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150
            )
            
            content = response.choices[0].message.content
            
            lines = content.split('\n')
            question = next((line.replace('Question: ', '') for line in lines 
                           if 'Question:' in line), None)
            answer = next((line.replace('Answer: ', '') for line in lines 
                          if 'Answer:' in line), None)
            
            if question and answer:
                return {
                    'question': question.strip(),
                    'answer': answer.strip(),
                    'source': 'trend'
                }
            
            return None

        except Exception as e:
            logger.warning(f"OpenAI creation failed: {e}")
            return None

    def _create_with_groq(self, prompt: str) -> Optional[Dict[str, str]]:
        """Create content with Groq"""
        try:
            from groq import Groq
            
            client = Groq(api_key=os.getenv('GROQ_API_KEY'))
            
            message = client.messages.create(
                model="mixtral-8x7b-32768",
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}]
            )
            
            content = message.content[0].text
            
            lines = content.split('\n')
            question = next((line.replace('Question: ', '') for line in lines 
                           if 'Question:' in line), None)
            answer = next((line.replace('Answer: ', '') for line in lines 
                          if 'Answer:' in line), None)
            
            if question and answer:
                return {
                    'question': question.strip(),
                    'answer': answer.strip(),
                    'source': 'trend'
                }
            
            return None

        except Exception as e:
            logger.warning(f"Groq creation failed: {e}")
            return None
