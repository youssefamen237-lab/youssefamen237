import os
import json
import random
import requests
from dotenv import load_dotenv

load_dotenv()

class ContentEngine:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.history_file = "data/history.json"
        self.prompts_file = "config/prompts.json"
        
    def load_history(self):
        if not os.path.exists(self.history_file):
            return {"published_questions": []}
        with open(self.history_file, 'r') as f:
            return json.load(f)

    def save_history(self, data):
        with open(self.history_file, 'w') as f:
            json.dump(data, f, indent=2)

    def generate_short_content(self):
        history = self.load_history()
        used_questions = history.get("published_questions", [])
        
        # Load prompts
        with open(self.prompts_file, 'r') as f:
            prompts = json.load(f)
        
        system_instruction = prompts["shorts_system"]
        
        # Anti-duplicate logic in prompt
        prompt = f"{system_instruction} Avoid these recent topics: {', '.join(used_questions[-5:])}"
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json"
            }
        }
        
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            content = json.loads(data['candidates'][0]['content']['parts'][0]['text'])
            
            # Validate content
            if 'question' not in content or 'correct_answer_index' not in content:
                raise ValueError("Invalid JSON structure from AI")
                
            # Update History
            history["published_questions"].append(content['question'])
            if len(history["published_questions"]) > 100:
                history["published_questions"] = history["published_questions"][-100:]
            self.save_history(history)
            
            return content
        except Exception as e:
            print(f"Content Generation Failed: {e}")
            # Fallback to hardcoded safe question if API fails
            return {
                "question": "What is the capital of France?",
                "options": ["Berlin", "Paris", "Madrid"],
                "correct_answer_index": 1,
                "category": "Geography"
            }

    def generate_seo(self, topic):
        with open(self.prompts_file, 'r') as f:
            prompts = json.load(f)
        
        prompt = prompts["seo_system"].replace("[TOPIC]", topic)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
        
        try:
            response = requests.post(url, json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"response_mime_type": "application/json"}
            })
            return json.loads(response.json()['candidates'][0]['content']['parts'][0]['text'])
        except:
            return {
                "titles": ["Amazing Fact You Didn't Know!", "Test Your Knowledge Now", "Viral Quiz Challenge"],
                "description": "Can you answer this? Subscribe for more daily quizzes! #shorts #quiz #trivia",
                "tags": ["quiz", "trivia", "facts", "learning", "shorts"]
            }
