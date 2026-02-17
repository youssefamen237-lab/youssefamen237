from groq import Groq
from config import Config
from utils.database import Database
import random

db = Database()
client = Groq(api_key=Config.GROQ_API_KEY)

CTA_PHRASES = [
    "If you know the answer before the 5 seconds end, drop it in the comments.",
    "Bet you can't get this right. Prove me wrong below.",
    "90% fail this. Are you in the 10%? Comment your answer.",
    "Pause if you need more time! Answer in comments.",
    "Think fast! Type your guess before the timer ends."
]

class ContentEngine:
    def __init__(self):
        self.template = Config.get_random_template()

    def generate_question(self):
        retries = 0
        while retries < Config.MAX_RETRIES:
            prompt = f"""
            Generate a viral YouTube Short trivia question for a {Config.TARGET_AUDIENCE} audience.
            Template: {self.template}
            Language: English (US/UK)
            
            Return JSON format only:
            {{
                "question": "The question text",
                "options": ["A", "B", "C"] (if applicable, else empty),
                "answer": "The correct answer",
                "explanation": "Short fun fact"
            }}
            Ensure the question is unique and not generic.
            """
            
            try:
                response = client.chat.completions.create(
                    model="llama3-70b-8192",
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"}
                )
                
                data = json.loads(response.choices[0].message.content)
                
                if not db.is_duplicate(data["question"]):
                    db.add_question(data["question"], self.template, data["answer"])
                    data["cta"] = random.choice(CTA_PHRASES)
                    return data
                else:
                    print("Duplicate detected, regenerating...")
                    retries += 1
            except Exception as e:
                print(f"Generation Error: {e}")
                retries += 1
        
        raise Exception("Failed to generate unique content after retries.")
