import hashlib
import json
import random
import google.generativeai as genai
from .config import Config

class ContentEngine:
    def __init__(self, strategy):
        self.strategy = strategy
        # إعداد Gemini بأحدث طريقة
        genai.configure(api_key=Config.GEMINI_KEY)
        # نستخدم gemini-1.5-flash مباشرة بدون بادئة models/ في بعض الإصدارات
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    def generate_hook(self):
        hooks = ["Only 1% can solve this!", "Are you a genius?", "I bet you fail this.", "99% get this wrong."]
        return random.choice(hooks)

    def generate_script(self):
        # طلب الرد بصيغة JSON صريحة
        prompt = f"""
        Generate a unique trivia question of type: {self.strategy['question_type']}.
        Return ONLY a JSON object with this exact structure:
        {{
            "question": "text",
            "options": ["A", "B", "C"],
            "answer": "correct_text",
            "answer_index": 0
        }}
        """
        
        try:
            # استخدام generation_config لضمان الحصول على JSON
            response = self.model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            
            if not response.text:
                raise Exception("Empty response from Gemini")

            content = json.loads(response.text)
            content['hook'] = self.generate_hook()
            content['cta'] = "Subscribe for more brain teasers!"
            
            # منع التكرار
            content_str = f"{content['question']}-{content['answer']}"
            content['hash'] = hashlib.sha256(content_str.encode()).hexdigest()
            
            return content
        except Exception as e:
            print(f"❌ Gemini Generation Error: {str(e)}")
            return None
