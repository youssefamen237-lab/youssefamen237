import random
from datetime import datetime
from typing import Dict

class HumanSimulator:
    def __init__(self, config: Dict):
        self.config = config
        self.state = self._load_state()
        
    def generate_video_params(self) -> Dict:
        """Randomized video parameters"""
        base_length = self.state.get('baseline_length', 20)
        base_speed = self.state.get('baseline_speed', 1.0)
        
        return {
            'duration': random.uniform(
                self.config['production']['video_length_range'][0],
                self.config['production']['video_length_range'][1]
            ),
            'voice_speed': random.uniform(0.95, 1.07),
            'text_position_variance': random.uniform(-5, 5),  # ±5%
            'timer_offset': random.uniform(-0.3, 0.3)
        }
    
    def generate_upload_metadata(self) -> Dict:
        """Varied metadata"""
        return {
            'title_variant': random.choice(['hook_first', 'emoji_heavy', 'question_format']),
            'description_length': random.choice(['short', 'medium', 'long']),
            'tags_count': random.randint(8, 15)
        }
    
    def _load_state(self):
        import json
        try:
            with open('data/strategy_state.json') as f:
                return json.load(f)
        except:
            return {}
