import os
import re
from typing import Dict, List
import google.generativeai as genai

class SafetyChecker:
    def __init__(self):
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        self.gemini = genai.GenerativeModel('gemini-pro')
        self.banned_words = self._load_banned_words()
        
    def _load_banned_words(self) -> List[str]:
        return [
            'death', 'kill', 'murder', 'war', 'terrorist', 'bomb', 'attack',
            'sex', 'porn', 'nude', 'naked', 'political', 'election', 'vote',
            'religion', 'god', 'allah', 'jesus', 'bible', 'quran',
            'suicide', 'drug', 'cocaine', 'heroin', 'weapon', 'gun', 'shoot'
        ]
    
    def validate(self, content: Dict) -> bool:
        """Multi-layer safety check"""
        text_to_check = f"{content['question']} {content['answer']} {content.get('explanation', '')}"
        text_lower = text_to_check.lower()
        
        # Layer 1: Keyword blacklist
        for word in self.banned_words:
            if word in text_lower:
                print(f"❌ Failed keyword check: {word}")
                return False
        
        # Layer 2: Pattern detection (flags, explicit symbols)
        if re.search(r'[\U0001F1E0-\U0001F1FF]', text_to_check):  # Country flags
            return False
            
        # Layer 3: AI Moderation (Gemini)
        try:
            prompt = f"""Analyze this content for safety. Reply with only "SAFE" or "UNSAFE":
            Content: {text_to_check}
            Check for: violence, sexual content, hate speech, self-harm, dangerous acts."""
            
            response = self.gemini.generate_content(prompt)
            result = response.text.strip().upper()
            
            if "UNSAFE" in result:
                return False
                
        except Exception as e:
            print(f"AI moderation failed: {e}")
            # Fail safe: if AI check fails, allow but log
            pass
            
        return True
