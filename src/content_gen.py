import hashlib
import json
import random
import google.generativeai as genai
from .config import Config

class ContentEngine:
    def __init__(self, strategy):
        self.strategy = strategy
        # إعداد جمناي
        genai.configure(api_key=Config.GEMINI_KEY)
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    def generate_hook(self):
        hooks = [
            "Only 1% can solve this!",
            "Are you a genius?",
            "I bet you fail this.",
            "99% get this wrong.",
            "Think you're smart? Try this."
        ]
        return random.choice(hooks)

    def generate_script(self):
        prompt = f"""
        Generate a unique, engaging trivia question. 
        Type: {self.strategy['question_type']}.
        Output MUST be in strictly valid JSON format like this:
        {{
            "question": "The question text",
            "options": ["Option A", "Option B", "Option C"],
            "answer": "The correct answer text",
            "answer_index": 0
        }}
        """
        
        try:
            # طلب التوليد من جمناي
            response = self.model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            
            content = json.loads(response.text)
            
            content['hook'] = self.generate_hook()
            content['cta'] = random.choice(["Subscribe for more!", "Comment your score!", "Share with a friend!"])
            
            # عمل Hash للمحتوى لمنع التكرار
            content_str = f"{content['question']}-{content['answer']}"
            content['hash'] = hashlib.sha256(content_str.encode()).hexdigest()
            
            return content
        except Exception as e:
            print(f"❌ Gemini Generation Error: {e}")
            return None
