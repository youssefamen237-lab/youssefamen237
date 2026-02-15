import requests
import google.generativeai as genai
from groq import Groq
from config import GEMINI_API_KEY, GROQ_API_KEY
import random

class AIContentGenerator:
    def __init__(self):
        if GEMINI_API_KEY:
            genai.configure(api_key=GEMINI_API_KEY)
            self.gemini_model = genai.GenerativeModel('gemini-pro')
        
        if GROQ_API_KEY:
            self.groq_client = Groq(api_key=GROQ_API_KEY)
            self.groq_model = "mixtral-8x7b-32768"
    
    def generate_question_and_answer(self, template_type):
        """Generate a question and answer based on the template type"""
        prompt = self._create_prompt_for_template(template_type)
        
        # Try different models until one works
        response = None
        
        # Try Gemini first
        if hasattr(self, 'gemini_model'):
            try:
                result = self.gemini_model.generate_content(prompt)
                response = result.text.strip()
            except Exception as e:
                print(f"Gemini failed: {e}")
        
        # Fallback to Groq
        if not response and hasattr(self, 'groq_client'):
            try:
                chat_completion = self.groq_client.chat.completions.create(
                    messages=[
                        {
                            "role": "user",
                            "content": prompt,
                        }
                    ],
                    model=self.groq_model,
                )
                response = chat_completion.choices[0].message.content.strip()
            except Exception as e:
                print(f"Groq failed: {e}")
        
        if not response:
            raise Exception("All AI models failed to generate content")
        
        # Parse the response to extract question and answer
        question, answer = self._parse_ai_response(response)
        return question, answer
    
    def _create_prompt_for_template(self, template_type):
        """Create a specific prompt based on the template type"""
        prompts = {
            'True / False': "Generate a true or false question about general knowledge, culture, science, or history. Provide the question and the correct answer. Format: QUESTION: [question text] ANSWER: [True/False]",
            'Multiple Choice': "Generate a multiple choice question with 4 options and the correct answer. Focus on general knowledge, culture, science, or history. Format: QUESTION: [question text] OPTIONS: A) [option1], B) [option2], C) [option3], D) [option4] ANSWER: [correct option letter]",
            'سؤال مباشر': "Generate a direct question about general knowledge, culture, science, or history that has a clear answer. Format: QUESTION: [question text] ANSWER: [answer text]",
            'Guess the Answer': "Generate a riddle or guessing question about general knowledge, culture, science, or history. Format: QUESTION: [riddle/guessing question] ANSWER: [answer text]",
            'Quick Challenge': "Generate a quick challenge or trivia question about general knowledge, culture, science, or history. Format: QUESTION: [challenge question] ANSWER: [answer text]",
            'Only Geniuses': "Generate a difficult question that only geniuses would know the answer to, about general knowledge, culture, science, or history. Format: QUESTION: [difficult question] ANSWER: [answer text]",
            'Memory Test': "Generate a memory test question about general knowledge, culture, science, or history. Format: QUESTION: [memory test question] ANSWER: [answer text]",
            'Visual Question': "Generate a question that could be represented visually but is asked in text form, about general knowledge, culture, science, or history. Format: QUESTION: [visual question] ANSWER: [answer text]"
        }
        
        base_prompt = prompts.get(template_type, prompts['سؤال مباشر'])
        
        # Add variation to prevent repetitive patterns
        variations = [
            "Make sure it's engaging and interesting.",
            "Ensure it's educational and informative.",
            "Focus on Western culture, American, British, or Canadian topics.",
            "Include diverse topics from around the world.",
            "Keep it challenging but fair."
        ]
        
        variation = random.choice(variations)
        return f"{base_prompt} {variation}"
    
    def _parse_ai_response(self, response):
        """Parse the AI response to extract question and answer"""
        lines = response.split('\n')
        
        question = ""
        answer = ""
        
        for line in lines:
            line = line.strip()
            
            if line.lower().startswith('question:'):
                question = line[len('question:'):].strip()
            elif 'question:' in line.lower():
                # Handle case where format is different
                parts = line.split('QUESTION:')
                if len(parts) > 1:
                    question = parts[1].split('ANSWER:')[0].strip()
            
            if line.lower().startswith('answer:'):
                answer = line[len('answer:'):].strip()
            elif 'answer:' in line.lower():
                parts = line.split('ANSWER:')
                if len(parts) > 1:
                    answer = parts[-1].strip()
        
        # If we couldn't parse properly, return the full response as question
        if not question or not answer:
            # Split the response into question and answer parts
            parts = response.split('ANSWER:')
            if len(parts) > 1:
                question = parts[0].replace('QUESTION:', '').strip()
                answer = parts[1].strip()
            else:
                question = response[:200]  # First 200 chars as question
                answer = "See description for answer"
        
        return question.strip(), answer.strip()
