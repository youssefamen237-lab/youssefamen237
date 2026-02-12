import json
import os
import random
import time
from .config import Config

class Brain:
    def __init__(self):
        self.perf_db_path = os.path.join(Config.DATA_DIR, 'performance_db.json')
        self.registry_path = os.path.join(Config.DATA_DIR, 'content_registry.json')
        self.upload_queue_path = os.path.join(Config.DATA_DIR, 'upload_queue.json')
        self.load_data()

    def load_data(self):
        with open(self.perf_db_path, 'r') as f: self.history = json.load(f)
        with open(self.registry_path, 'r') as f: self.registry = json.load(f)

    def save_data(self):
        with open(self.perf_db_path, 'w') as f: json.dump(self.history, f, indent=4)
        with open(self.registry_path, 'w') as f: json.dump(self.registry, f, indent=4)

    def check_shadowban(self):
        # Logic: If last 3 videos averaged < 100 views (Simulated logic for now)
        if not self.history: return False
        recent = self.history[-3:]
        views = [x.get('views', 0) for x in recent]
        if views and (sum(views) / len(views)) < 50:
            print("⚠️ Shadowban Suspected! Pausing.")
            return True
        return False

    def get_strategy(self):
        # Adaptive Logic
        strategy = {
            "voice_gender": "female",
            "voice_speed": 1.1,
            "duration_target": 18,
            "question_type": "riddle"
        }
        
        if self.history:
            # Analyze best performing gender
            m_score = sum([x['score'] for x in self.history if x['meta']['gender'] == 'male'])
            f_score = sum([x['score'] for x in self.history if x['meta']['gender'] == 'female'])
            if m_score > f_score: strategy['voice_gender'] = 'male'
            
            # Apply Drift
            if random.random() < 0.1: # 10% chance to mutate
                strategy['voice_speed'] += random.uniform(-0.05, 0.05)
        
        return strategy

    def is_duplicate(self, question_hash):
        current_time = time.time()
        for item in self.registry:
            if item['hash'] == question_hash:
                # 15 Days check (15 * 24 * 3600 = 1296000)
                if (current_time - item['timestamp']) < 1296000:
                    return True
        return False

    def register_content(self, meta_data):
        self.registry.append({
            "hash": meta_data['hash'],
            "timestamp": time.time(),
            "meta": meta_data
        })
        self.save_data()
