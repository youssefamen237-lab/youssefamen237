import os
import random
import hashlib
from typing import Dict, Optional
import google.generativeai as genai
from groq import Groq

from utils import logger, load_json

class ContentGenerator:
    def __init__(self, config: Dict):
        self.config = config
        self.templates = config['templates']
        self.hooks = config['hooks']
        self.ctas = config['ctas']
        
        # Initialize APIs
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        self.gemini = genai.GenerativeModel('gemini-pro')
        self.groq = Groq(api_key=os.getenv('GROQ_API_KEY'))
        
    def generate(self, trend_context: Optional[Dict] = None) -> Dict:
        """Generate unique short content"""
        template = random.choice(self.templates)
        hook = random.choice(self.hooks)
        cta = random.choice(self.ctas)
        voice_gender = self._select_voice_gender()
        
        # Generate question based on template
        question_data = self._generate_question(template, trend_context)
        
        content = {
            'template': template,
            'hook': hook,
            'question': question_data['question'],
            'answer': question_data['answer'],
            'options': question_data.get('options', []),
            'explanation': question_data.get('explanation', ''),
            'cta': cta,
            'voice_gender': voice_gender,
            'timer_duration': random.uniform(4.8, 5.3),
            'content_hash': None  # Will be calculated
        }
        
        content['content_hash'] = self._calculate_hash(content)
        return content
    
    def _generate_question(self, template: str, trend_context: Optional[Dict]) -> Dict:
        """AI-powered question generation"""
        trend_text = ""
        if trend_context:
            trend_text = f"Context: Current trending topic is {trend_context['topic']}. Incorporate subtly if relevant."
            
        prompts = {
            'true_false': f"""Generate a tricky True/False trivia question. {trend_text}
            Make it surprising and counter-intuitive.
            Format: {{"question": "...", "answer": "True" or "False", "explanation": "..."}}""",
            
            'multiple_choice': f"""Generate a multiple choice brain teaser with 4 options. {trend_text}
            Only one correct answer. Make it challenging.
            Format: {{"question": "...", "options": ["A) ...", "B) ...", "C) ...", "D) ..."], "answer": "A", "explanation": "..."}}""",
            
            'quick_solve': f"""Generate a quick math or logic puzzle solvable in 5 seconds. {trend_text}
            Format: {{"question": "...", "answer": "...", "explanation": "..."}}""",
            
            'visual_difference': """Generate a description of a visual puzzle (spot the difference concept).
            Format: {"question": "Spot the odd one out...", "answer": "Description of solution", "visual_elements": [...]}""",
            
            'memory_test': """Generate a short memory challenge (remember 3-4 items).
            Format: {"question": "Remember these...", "answer": "The items", "display_time": 3}"""
        }
        
        prompt = prompts.get(template, prompts['true_false'])
        
        try:
            # Try Groq first (faster, cheaper)
            response = self.groq.chat.completions.create(
                model="mixtral-8x7b-32768",
                messages=[{"role": "system", "content": "You are a content creator for viral brain teasers."},
                          {"role": "user", "content": prompt}],
                temperature=0.8,
                max_tokens=300
            )
            text = response.choices[0].message.content
        except:
            # Fallback to Gemini
            response = self.gemini.generate_content(prompt)
            text = response.text
            
        # Parse JSON-like response (simplified)
        import json
        try:
            # Extract JSON from potential markdown
            if '```json' in text:
                text = text.split('```json')[1].split('```')[0]
            elif '```' in text:
                text = text.split('```')[1].split('```')[0]
            data = json.loads(text)
        except:
            # Fallback parsing
            data = {
                'question': text[:150] + "?",
                'answer': "True",
                'explanation': "Logic puzzle"
            }
            
        return data
    
    def _select_voice_gender(self) -> str:
        """Weighted selection based on performance history"""
        profiles = self.config['voice_profiles']
        weights = [profiles['male']['probability'], profiles['female']['probability']]
        return random.choices(['male', 'female'], weights=weights)[0]
    
    def _calculate_hash(self, content: Dict) -> str:
        """Generate unique hash for content"""
        text = f"{content['template']}{content['question']}{content['answer']}"
        return hashlib.md5(text.encode()).hexdigest()
    
    def inject_trend(self) -> Dict:
        """Get trending topic every 3 days"""
        try:
            from serpapi import GoogleSearch
            
            params = {
                "q": "trending topics 2024",
                "tbm": "trending",
                "api_key": os.getenv('SERPAPI')
            }
            
            search = GoogleSearch(params)
            results = search.get_dict()
            
            if 'trending_searches' in results:
                topic = results['trending_searches'][0]['title']
                return {'topic': topic, 'injected': True}
        except Exception as e:
            logger.warning(f"Trend injection failed: {e}")
            
        return {'topic': 'general', 'injected': False}
