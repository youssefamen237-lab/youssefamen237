import google.generativeai as genai
import json
import random
from src.config import GEMINI_API_KEY
from src.database import is_question_used

genai.configure(api_key=GEMINI_API_KEY)

TEMPLATES = [
    "True / False", "Multiple Choice", "Direct Question", 
    "Guess the Answer", "Quick Challenge", "Only Geniuses", 
    "Memory Test", "Visual Question"
]

def generate_content(is_long=False):
    model = genai.GenerativeModel('gemini-pro')
    template = random.choice(TEMPLATES)
    
    count = 50 if is_long else 1
    
    prompt = f"""
    You are an expert YouTube scriptwriter. Generate {count} unique trivia question(s) for a US/UK audience.
    Template style: {template}.
    Do NOT repeat common questions. Make it engaging.
    Output strictly in JSON format:
    {{
        "seo_title": "Catchy YouTube Title",
        "seo_desc": "SEO optimized description with CTA",
        "tags": ["tag1", "tag2"],
        "questions": [
            {{
                "question": "The question text?",
                "options": ["A", "B", "C", "D"], 
                "answer": "The correct answer",
                "trivia": "A short interesting fact about the answer"
            }}
        ]
    }}
    """
    
    for _ in range(3): # Retry logic
        try:
            response = model.generate_content(prompt)
            data = json.loads(response.text.replace("```json", "").replace("```", "").strip())
            
            # Check 15-day rule for shorts
            if not is_long and is_question_used(data["questions"][0]["question"]):
                continue
                
            return data, template
        except Exception as e:
            print(f"AI Generation failed, retrying... {e}")
            continue
    raise Exception("Failed to generate unique content after 3 attempts.")
