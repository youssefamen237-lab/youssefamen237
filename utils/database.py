import json
import os
from datetime import datetime, timedelta

DB_FILE = "content_history.json"

class Database:
    def __init__(self):
        if not os.path.exists(DB_FILE):
            self.data = {"questions": [], "performance": []}
            self.save()
        else:
            with open(DB_FILE, 'r') as f:
                self.data = json.load(f)

    def save(self):
        with open(DB_FILE, 'w') as f:
            json.dump(self.data, f, indent=4)

    def is_duplicate(self, question_text):
        # Check if question exists in last 15 days
        cutoff = datetime.now() - timedelta(days=15)
        for entry in self.data["questions"]:
            if entry["text"] == question_text and datetime.fromisoformat(entry["date"]) > cutoff:
                return True
        return False

    def add_question(self, question_text, template, answer):
        self.data["questions"].append({
            "text": question_text,
            "template": template,
            "answer": answer,
            "date": datetime.now().isoformat(),
            "views": 0, # Will be updated by manager
            "likes": 0
        })
        self.save()

    def update_stats(self, video_id, views, likes):
        for entry in self.data["questions"]:
            # Simplified matching logic for demo
            if entry.get("video_id") == video_id:
                entry["views"] = views
                entry["likes"] = likes
        self.save()

    def get_best_performing_template(self):
        # Logic to analyze which template gets most views
        # Placeholder for Manager logic
        return "Multiple Choice"
