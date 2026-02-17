import json
import os
import random

class Manager:
    def __init__(self):
        self.state_file = "data/state.json"
        self.history_file = "data/history.json"
        
    def load_state(self):
        with open(self.state_file, 'r') as f:
            return json.load(f)
            
    def save_state(self, state):
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)
            
    def analyze_and_adjust(self, stats):
        state = self.load_state()
        views = int(stats.get('viewCount', 0))
        
        # Logic: If views are low, change strategy
        if views < 100:
            print("Low performance detected. Rotating strategy.")
            templates = ["t1", "t2", "t3", "t4"]
            state['preferred_template_id'] = random.choice([t for t in templates if t != state['preferred_template_id']])
            state['risk_level'] = "high" # Try bolder titles
        else:
            print("Performance good. Maintaining strategy.")
            state['risk_level'] = "low"
            
        self.save_state(state)
        return state
