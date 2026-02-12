import hashlib
import json
import random
from openai import OpenAI
from .config import Config

client = OpenAI(api_key=Config.OPENAI_KEY)

TEMPLATES = [
    "Riddle: {question}",
    "True or False: {question}",
    "Find the odd one out: {question}",
    "Quick Math: {question}"
]

class ContentEngine:
    def __init__(self, strategy):
        self.strategy = strategy

    def generate_hook(self):
        hooks = [
            "Only 1% can solve this!",
            "Are you a genius?",
            "I bet you fail this.",
            "99% get this wrong."
        ]
        return random.choice(hooks)

    def generate_script(self):
        # Generate Trivia using OpenAI
        prompt = f"""
        Generate a unique, engaging trivia question. 
        Type: {self.strategy['question_type']}.
        Output JSON format: {{
            "question": "The question text",
            "options": ["A", "B", "C"],
            "answer": "The correct answer",
            "answer_index": 0 (0, 1, or 2)
        }}
        """
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            content = json.loads(response.choices[0].message.content)
            
            content['hook'] = self.generate_hook()
            content['cta'] = random.choice(["Subscribe for more!", "Comment your score!"])
            
            # Create Hash
            content_str = f"{content['question']}-{content['answer']}"
            content['hash'] = hashlib.sha256(content_str.encode()).hexdigest()
            
            return content
        except Exception as e:
            print(f"Error generating content: {e}")
            return None
