import os
import random
import json
import google.generativeai as genai
import logging

class GenerativeAI:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        genai.configure(api_key=self.api_key)
        self.templates =[
            "True or False", "Multiple Choice", "Direct Question",
            "Guess the Hidden Subject", "Only Geniuses Can Solve",
            "5-Second Visual Puzzle", "Find the Lie", "Finish the Sentence"
        ]
        
    def generate_quiz_script(self, db_manager):
        template = random.choice(self.templates)
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        
        prompt = f"""
        Act as a professional viral YouTube Shorts creator targeting an English-speaking audience (USA/UK/CA).
        Create ONE extremely highly engaging short video script following this strict format. 
        Category: {template}. 
        Requirements:
        1. Unique, never seen trivia/question that will shock or entertain.
        2. Give 2-4 short options if applicable. 
        3. A CTA sentence like 'Drop it in the comments!' customized.
        4. Output format: PURE VALID JSON with no codeblock markers (`).
        Format:
        {{
            "template": "{template}",
            "question": "Question text...",
            "options": ["A", "B", "C"], # list, empty if True/False
            "answer": "Correct answer exactly from options",
            "cta": "Engaging hook/cta phrase...",
            "topic": "nature or science or history or entertainment",
            "post_answer_trivia": "Fun brief 1-line fact about the answer"
        }}
        """
        try:
            for _ in range(5):  # Safety loop for duplicates
                response = model.generate_content(prompt).text
                # strip json formatting if model added it
                cleaned = response.replace("```json", "").replace("```", "").strip()
                data = json.loads(cleaned)
                
                if not db_manager.is_duplicate(data['question']):
                    return data
            return None # Failsafe
        except Exception as e:
            logging.error(f"AI Gen Error: {e}")
            return None

    def generate_seo_metadata(self, quiz_data, is_long=False):
        topic = quiz_data.get('topic', 'fun challenge')
        
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        kind = "Long viral quiz video" if is_long else "Viral Short"
        
        prompt = f"""
        Generate YouTube metadata for a {kind} about '{topic}'. Target Audience: American. 
        Return raw valid JSON ONLY with exactly these keys: 
        'title' (strong, engaging, max 50 chars for Shorts), 
        'description' (2 paragraphs + safe terms),
        'tags' (array of 10 relevant strings).
        """
        response = model.generate_content(prompt).text.replace("```json", "").replace("```", "").strip()
        try:
             return json.loads(response)
        except:
             # Deep Failover system. Never fail.
             return {
                 "title": "You won't get this one! 🤔 #shorts",
                 "description": f"Challenge yourself! We upload best mind tests daily.",
                 "tags": ["shorts", "quiz", "trivia", topic]
             }
