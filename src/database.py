import json
import os
from datetime import datetime, timedelta
from src.config import DB_FILE

def load_db():
    if not os.path.exists(DB_FILE):
        return {"used_questions": [], "analytics": {}, "strategy": {"best_template": "Multiple Choice", "best_length": 15}}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def is_question_used(question_text):
    db = load_db()
    for q in db["used_questions"]:
        if q["text"] == question_text:
            date_used = datetime.fromisoformat(q["date"])
            if datetime.now() - date_used < timedelta(days=15):
                return True
    return False

def add_used_question(question_text, template):
    db = load_db()
    db["used_questions"].append({
        "text": question_text,
        "template": template,
        "date": datetime.now().isoformat()
    })
    save_db(db)
