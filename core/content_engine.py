import os
import json
import random
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

import google.generativeai as genai
from groq import Groq
import httpx
from dotenv import load_dotenv

load_dotenv()

class ContentEngine:
    def __init__(self):
        self.load_api_keys()
        self.question_bank = self.load_question_bank()
        self.templates = self.load_templates()
        self.last_used_questions = {}
        self.used_templates = []
        self.current_template = None
        self.logger = self.setup_logger()
        
    def setup_logger(self):
        logger = logging.getLogger('ContentEngine')
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler('logs/system.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def load_api_keys(self):
        self.gemini_key = os.getenv('GEMINI_API_KEY')
        self.groq_key = os.getenv('GROQ_API_KEY')
        self.hf_token = os.getenv('HF_API_TOKEN')
        
        if self.gemini_key:
            genai.configure(api_key=self.gemini_key)
        
        self.groq_client = Groq(api_key=self.groq_key) if self.groq_key else None

    def load_question_bank(self) -> Dict:
        try:
            with open('data/question_bank/active_questions.json', 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"questions": []}

    def save_question_bank(self, bank: Dict):
        with open('data/question_bank/active_questions.json', 'w') as f:
            json.dump(bank, f, indent=2)

    def load_templates(self) -> Dict:
        templates = {}
        templates_dir = 'data/templates/'
        
        for template_file in os.listdir(templates_dir):
            if template_file.endswith('.json'):
                with open(os.path.join(templates_dir, template_file), 'r') as f:
                    template_name = template_file.replace('.json', '')
                    templates[template_name] = json.load(f)
                    
        return templates

    def select_template(self) -> str:
        available_templates = list(self.templates.keys())
        
        # Remove recently used templates to ensure rotation
        if len(self.used_templates) >= 3:
            for template in self.used_templates[-3:]:
                if template in available_templates:
                    available_templates.remove(template)
        
        # Ensure we have at least 8 templates as required
        if len(available_templates) < 8 and len(self.templates) >= 8:
            # Reset used templates if we've cycled through most
            self.used_templates = []
            available_templates = list(self.templates.keys())
            
        self.current_template = random.choice(available_templates)
        self.used_templates.append(self.current_template)
        
        # Keep track of only the last 10 used templates
        if len(self.used_templates) > 10:
            self.used_templates.pop(0)
            
        return self.current_template

    def generate_question(self) -> Dict:
        """Generate a new question using available AI models with fallback system"""
        template = self.select_template()
        self.logger.info(f"Selected template: {template}")
        
        # Check if we can use question from bank first (to ensure accuracy)
        question_from_bank = self.get_question_from_bank(template)
        if question_from_bank:
            self.logger.info("Using question from verified bank")
            return question_from_bank
            
        # Try different AI models in sequence with fallback
        question_data = self._try_gemini(template)
        
        if not question_data or not self.validate_question(question_data):
            self.logger.warning("Gemini failed, trying Groq")
            question_data = self._try_groq(template)
            
        if not question_data or not self.validate_question(question_data):
            self.logger.warning("Groq failed, trying fallback API")
            question_data = self._try_fallback_api(template)
            
        if not question_data or not self.validate_question(question_data):
            self.logger.error("All AI services failed, using emergency question")
            question_data = self.get_emergency_question(template)
            
        # Add to question bank for verification
        self.add_to_question_bank(question_data, template)
        
        return question_data

    def _try_gemini(self, template: str) -> Optional[Dict]:
        if not self.gemini_key:
            return None
            
        try:
            model = genai.GenerativeModel('gemini-pro')
            prompt = self._build_prompt(template)
            
            response = model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.7,
                    "top_p": 0.8,
                    "top_k": 40,
                    "max_output_tokens": 500
                }
            )
            
            return self._parse_response(response.text, template)
        except Exception as e:
            self.logger.error(f"Gemini error: {str(e)}")
            return None

    def _try_groq(self, template: str) -> Optional[Dict]:
        if not self.groq_client:
            return None
            
        try:
            prompt = self._build_prompt(template)
            
            chat_completion = self.groq_client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a question generator for YouTube Shorts. Create engaging, accurate questions."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model="mixtral-8x7b-32768",
                temperature=0.7,
                max_tokens=500
            )
            
            return self._parse_response(chat_completion.choices[0].message.content, template)
        except Exception as e:
            self.logger.error(f"Groq error: {str(e)}")
            return None

    def _try_fallback_api(self, template: str) -> Optional[Dict]:
        apis = [
            ('OPENAI_API_KEY', 'https://api.openai.com/v1/chat/completions', 'gpt-3.5-turbo'),
            ('TAVILY_API_KEY', 'https://api.tavily.com/answers', None),
            ('ZENSERP', 'https://app.zenserp.com/api/v2/search', None)
        ]
        
        for api_env, url, model in apis:
            api_key = os.getenv(api_env)
            if not api_key:
                continue
                
            try:
                headers = {"Authorization": f"Bearer {api_key}"} if 'openai' in url else {"apikey": api_key}
                
                if 'openai' in url:
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "Create YouTube Shorts questions"},
                            {"role": "user", "content": self._build_prompt(template)}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 500
                    }
                    response = httpx.post(url, json=payload, headers=headers, timeout=30.0)
                else:
                    # Different API structure for non-OpenAI services
                    params = {
                        "q": f"Generate YouTube Shorts {template} question",
                        "search_engine": "google"
                    }
                    response = httpx.get(url, params=params, headers=headers, timeout=30.0)
                
                if response.status_code == 200:
                    if 'openai' in url:
                        content = response.json()['choices'][0]['message']['content']
                        return self._parse_response(content, template)
                    else:
                        # Handle other API responses
                        return self._parse_response(str(response.json()), template)
                        
            except Exception as e:
                self.logger.error(f"API {api_env} error: {str(e)}")
                continue
                
        return None

    def _build_prompt(self, template: str) -> str:
        base_prompts = {
            "true_false": "Generate a true/false question about general knowledge that is interesting and not too obvious. Format as: QUESTION: [question text] ANSWER: TRUE/FALSE EXPLANATION: [brief explanation]",
            "multiple_choice": "Generate a multiple choice question with 4 options (A, B, C, D) about world culture. Format as: QUESTION: [question] A: [option] B: [option] C: [option] D: [option] ANSWER: [correct letter] EXPLANATION: [brief explanation]",
            "direct_question": "Generate a direct question about entertainment trivia that most people might not know. Format as: QUESTION: [question] ANSWER: [answer] EXPLANATION: [brief explanation]",
            "guess_answer": "Create a 'Guess the Answer' question where viewers need to identify something from a description. Format as: QUESTION: [description] ANSWER: [answer] EXPLANATION: [brief explanation]",
            "quick_challenge": "Create a quick challenge question that tests general knowledge in under 5 seconds. Format as: QUESTION: [challenge description] ANSWER: [answer] EXPLANATION: [brief explanation]",
            "only_geniuses": "Create a question labeled 'Only Geniuses Can Answer This' that is challenging but fair. Format as: QUESTION: [question] ANSWER: [answer] EXPLANATION: [brief explanation]",
            "memory_test": "Create a memory test question where viewers need to remember specific details. Format as: QUESTION: [memory challenge] ANSWER: [answer] EXPLANATION: [brief explanation]",
            "visual_question": "Create a question that would work well with a visual element (though we won't describe the visual). Format as: QUESTION: [question] ANSWER: [answer] EXPLANATION: [brief explanation]"
        }
        
        return base_prompts.get(template, f"Generate a YouTube Shorts question using the {template} format. Format as: QUESTION: [question] ANSWER: [answer] EXPLANATION: [brief explanation]")

    def _parse_response(self, response_text: str, template: str) -> Dict:
        """Parse AI response into structured question data"""
        question_data = {
            "template": template,
            "question_text": "",
            "options": [],
            "answer": "",
            "explanation": "",
            "category": self._get_category_from_template(template),
            "difficulty": self._determine_difficulty(template),
            "verified": False,
            "used_count": 0,
            "last_used": None,
            "created_at": datetime.now().isoformat()
        }
        
        # Extract question
        if "QUESTION:" in response_text:
            question_part = response_text.split("QUESTION:")[1].split("\n")[0].strip()
            question_data["question_text"] = question_part
            
            # Extract options for multiple choice
            if template == "multiple_choice":
                for opt in ['A:', 'B:', 'C:', 'D:']:
                    if opt in response_text:
                        option_text = response_text.split(opt)[1].split("\n")[0].strip()
                        question_data["options"].append(option_text)
            
            # Extract answer
            if "ANSWER:" in response_text:
                answer_part = response_text.split("ANSWER:")[1].split("\n")[0].strip()
                question_data["answer"] = answer_part
            
            # Extract explanation
            if "EXPLANATION:" in response_text:
                explanation_part = response_text.split("EXPLANATION:")[1].strip()
                question_data["explanation"] = explanation_part[:200]  # Limit explanation length
        
        return question_data

    def _get_category_from_template(self, template: str) -> str:
        category_map = {
            "true_false": "general_knowledge",
            "multiple_choice": "world_culture",
            "direct_question": "entertainment",
            "guess_answer": "trivia",
            "quick_challenge": "general_knowledge",
            "only_geniuses": "challenging",
            "memory_test": "memory",
            "visual_question": "visual"
        }
        return category_map.get(template, "miscellaneous")

    def _determine_difficulty(self, template: str) -> str:
        difficulty_map = {
            "true_false": "medium",
            "multiple_choice": "medium",
            "direct_question": "medium",
            "guess_answer": "hard",
            "quick_challenge": "easy",
            "only_geniuses": "hard",
            "memory_test": "medium",
            "visual_question": "medium"
        }
        return difficulty_map.get(template, "medium")

    def validate_question(self, question_data: Dict) -> bool:
        """Validate that the question meets quality standards"""
        if not question_data["question_text"] or len(question_data["question_text"]) < 10:
            return False
            
        if not question_data["answer"] or len(question_data["answer"]) < 1:
            return False
            
        # Check for duplicate content
        if self.is_duplicate_question(question_data["question_text"]):
            return False
            
        # Check question length appropriate for Shorts
        if len(question_data["question_text"]) > 100:
            return False
            
        return True

    def is_duplicate_question(self, new_question: str, threshold: float = 0.85) -> bool:
        """Check if question is too similar to recently used ones"""
        for question in self.question_bank["questions"]:
            # Simple similarity check (in production, would use more sophisticated method)
            if self._text_similarity(new_question, question["question_text"]) > threshold:
                days_since_used = (datetime.now() - datetime.fromisoformat(question["last_used"])).days
                if days_since_used < 15:  # Requirement: no repeat before 15 days
                    return True
        return False

    def _text_similarity(self, text1: str, text2: str) -> float:
        """Simple text similarity check (would use more advanced in production)"""
        set1 = set(text1.lower().split())
        set2 = set(text2.lower().split())
        intersection = set1 & set2
        union = set1 | set2
        return len(intersection) / len(union) if union else 0

    def get_question_from_bank(self, template: str) -> Optional[Dict]:
        """Get a verified question from the bank if available"""
        eligible_questions = [
            q for q in self.question_bank["questions"]
            if q["template"] == template
            and q["verified"]
            and (not q.get("last_used") or (datetime.now() - datetime.fromisoformat(q["last_used"])).days >= 3)
        ]
        
        if eligible_questions:
            # Prioritize questions with lower usage count
            eligible_questions.sort(key=lambda x: x.get("used_count", 0))
            selected = eligible_questions[0]
            selected["used_count"] = selected.get("used_count", 0) + 1
            selected["last_used"] = datetime.now().isoformat()
            self.save_question_bank(self.question_bank)
            return selected
            
        return None

    def add_to_question_bank(self, question_data: Dict, template: str):
        """Add new question to bank for future verification"""
        if not self.validate_question(question_data):
            return
            
        # Ensure it's not a duplicate
        if any(q["question_text"] == question_data["question_text"] 
               for q in self.question_bank["questions"]):
            return
            
        question_data["template"] = template
        question_data["verified"] = False  # Needs verification before reuse
        self.question_bank["questions"].append(question_data)
        self.save_question_bank(self.question_bank)

    def get_emergency_question(self, template: str) -> Dict:
        """Return a safe emergency question when all else fails"""
        emergency_questions = {
            "true_false": {
                "question_text": "The Great Wall of China is visible from space with the naked eye.",
                "answer": "FALSE",
                "explanation": "This is a common myth, but the Great Wall is not visible from space without aid."
            },
            "multiple_choice": {
                "question_text": "Which planet is known as the Red Planet?",
                "options": ["Venus", "Mars", "Jupiter", "Saturn"],
                "answer": "B",
                "explanation": "Mars is known as the Red Planet due to its reddish appearance from iron oxide on its surface."
            },
            # Additional emergency questions for other templates
            # ... (would include at least one for each template type)
        }
        
        base = emergency_questions.get(template, {
            "question_text": "What is the capital of France?",
            "answer": "Paris",
            "explanation": "Paris has been the capital of France since the 10th century."
        })
        
        return {
            "template": template,
            "question_text": base["question_text"],
            "options": base.get("options", []),
            "answer": base["answer"],
            "explanation": base["explanation"],
            "category": self._get_category_from_template(template),
            "difficulty": "easy",
            "verified": True,
            "emergency": True,
            "created_at": datetime.now().isoformat()
        }

    def generate_cta(self) -> str:
        """Generate a variable CTA that changes each time"""
        cta_variations = [
            "If you knew the answer before the 5 seconds ended, drop it in the comments!",
            "Did you get it right? Let us know in the comments below!",
            "How many did you get correct? Share your score in the comments!",
            "Think you're smarter than most? Prove it in the comments!",
            "Got it on the first try? Drop a comment if you did!",
            "Only 10% get this right - did you? Tell us below!",
            "Challenge: Can you answer this in under 5 seconds? Comment your time!",
            "This stumped 90% of people - did it get you too? Let us know!"
        ]
        
        return random.choice(cta_variations)
