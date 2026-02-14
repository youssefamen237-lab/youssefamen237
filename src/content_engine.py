import google.generativeai as genai
from groq import Groq
import random
from src.config import GEMINI_API_KEY, GROQ_API_KEY
from src.utils import is_question_used

class ContentEngine:
    def __init__(self):
        self.templates = [
            "True or False",
            "Multiple Choice",
            "Direct Question",
            "Guess the Answer",
            "Quick Challenge",
            "Only Geniuses",
            "Memory Test",
            "Visual Question"
        ]
        if GEMINI_API_KEY:
            genai.configure(api_key=GEMINI_API_KEY)
            self.model = genai.GenerativeModel('gemini-pro')
        else:
            self.model = None
        
        self.groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

    def generate_question(self):
        template = random.choice(self.templates)
        prompt = (
            f"Generate a unique trivia question for a YouTube Short targeting US/UK audience. "
            f"Format: Template: {template}. "
            f"Return strictly in JSON format: {{'question': '...', 'answer': '...', 'options': ['...', '...'] if MCQ else [], 'explanation': '...'}}. "
            f"Make it engaging. Avoid repetition."
        )
        
        content = None
        # Primary: Gemini
        if self.model:
            try:
                response = self.model.generate_content(prompt)
                # Basic cleaning of response
                text = response.text.strip().replace("```json", "").replace("```", "")
                content = eval(text) # Use json.loads in production ideally
            except Exception as e:
                print(f"Gemini failed: {e}")
        
        # Fallback: Groq (Llama)
        if not content and self.groq_client:
            try:
                chat_completion = self.groq_client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model="llama3-8b-8192",
                )
                text = chat_completion.choices[0].message.content.strip()
                content = eval(text)
            except Exception as e:
                print(f"Groq failed: {e}")

        if content and not is_question_used(content.get('question')):
            content['template'] = template
            return content
        
        return None # Retry logic needed in main loop

    def generate_cta(self):
        ctas = [
            "Drop your answer in the comments before time runs out!",
            "Think you know it? Comment below!",
            "Only 5 seconds! Comment the answer now.",
            "If you get this right, you're a genius! Comment it."
        ]
        return random.choice(ctas)
