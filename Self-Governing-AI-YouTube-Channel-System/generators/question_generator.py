import random
import sqlite3
from database.db import is_question_used, mark_question_as_used

# Sample question database - in a real system, this would connect to an LLM or API
SAMPLE_QUESTIONS = [
    "What is the capital of France?",
    "Who invented the telephone?",
    "How many planets are in our solar system?",
    "What is the largest mammal?",
    "When was the internet invented?",
    "What is the chemical symbol for gold?",
    "Who painted the Mona Lisa?",
    "What is the longest river in the world?",
    "How many bones are in the human body?",
    "What is the hardest natural substance on Earth?",
    "Who wrote 'Romeo and Juliet'?",
    "What is the smallest country in the world?",
    "How many sides does a hexagon have?",
    "What is the fastest land animal?",
    "Who discovered penicillin?",
    "What is the largest ocean on Earth?",
    "How many days are in a leap year?",
    "What is the main ingredient in guacamole?",
    "Who was the first president of the United States?",
    "What is the largest organ in the human body?"
]

# Enhanced question generator with anti-duplication

def generate_unique_question():
    """Generate a unique question that hasn't been used before"""
    # Try up to 10 times to find a unique question
    for _ in range(10):
        # Pick a random question from our sample database
        question = random.choice(SAMPLE_QUESTIONS)
        
        # Check if this question has been used before
        if not is_question_used(question):
            # Mark it as used
            if mark_question_as_used(question):
                return question
    
    # If we couldn't find a unique question, return a fallback
    return "What is the meaning of life?"


def generate_multiple_questions(count=5):
    """Generate multiple unique questions"""
    questions = []
    for _ in range(count):
        question = generate_unique_question()
        if question not in questions:  # Additional deduplication
            questions.append(question)
    return questions


def generate_question_with_context(context="general"):
    """Generate a question based on a specific context"""
    # In a real implementation, this would use LLMs or APIs
    base_question = generate_unique_question()
    return base_question

# Test the question generator
if __name__ == '__main__':
    print("Generating test questions:")
    for i in range(5):
        q = generate_unique_question()
        print(f"Question {i+1}: {q}")
