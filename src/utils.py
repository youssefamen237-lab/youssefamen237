import json
import os
from datetime import datetime, timedelta

HISTORY_FILE = "data/history.json"
PERFORMANCE_FILE = "data/performance.json"

def load_json(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_json(filepath, data):
    # === الإصلاح: إنشاء المجلد إذا لم يكن موجوداً ===
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=4)

def get_history():
    return load_json(HISTORY_FILE)

def update_history(video_id, question, template, date_str):
    history = get_history()
    history[video_id] = {
        "question": question,
        "template": template,
        "date": date_str
    }
    save_json(HISTORY_FILE, history)

def is_question_used(question):
    history = get_history()
    # Check last 15 days logic simplified
    for vid, data in history.items():
        if data['question'] == question:
            return True
    return False
