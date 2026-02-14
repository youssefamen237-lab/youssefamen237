import json
import os
from datetime import datetime, timedelta

HISTORY_FILE = "data/history.json"
PERFORMANCE_FILE = "data/performance.json"

def load_json(filepath):
    if not os.path.exists(filepath):
        return {}
    with open(filepath, 'r') as f:
        return json.load(f)

def save_json(filepath, data):
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
    fifteen_days_ago = datetime.now() - timedelta(days=15)
    
    for vid, data in history.items():
        # Check exact match or high similarity (simplified here)
        if data['question'] == question:
            return True
    return False
