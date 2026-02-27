import json
import os
import time

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db = {"history":[], "analytics": {}}
        self._load()

    def _load(self):
        if os.path.exists(self.db_path):
            with open(self.db_path, "r", encoding="utf-8") as f:
                self.db = json.load(f)

    def _save(self):
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self.db, f, indent=4, ensure_ascii=False)

    def is_duplicate(self, text, safe_days=15):
        current_time = time.time()
        for item in self.db["history"]:
            if text.lower().strip() == item["q"].lower().strip():
                days_diff = (current_time - item["timestamp"]) / (24 * 3600)
                if days_diff < safe_days:
                    return True
        return False

    def log_question(self, text, type):
        self.db["history"].append({
            "q": text,
            "type": type,
            "timestamp": time.time()
        })
        self._save()

    def get_past_questions(self, days=7):
        current_time = time.time()
        return [i["q"] for i in self.db["history"] if (current_time - i["timestamp"]) / (24 * 3600) <= days]

    def cleanup_memory(self):
        # Cleans db to prevent endless growing json, keeping only 30 days history.
        curr = time.time()
        self.db["history"] =[i for i in self.db["history"] if (curr - i["timestamp"]) / (24 * 3600) < 30]
        self._save()
