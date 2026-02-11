import random
import json
from datetime import datetime
from typing import Dict

from utils import load_json, save_json, logger

class StrategyEngine:
    def __init__(self, config: Dict):
        self.config = config
        self.state_file = 'data/strategy_state.json'
        
    def evolve(self):
        """Adapt strategy based on performance"""
        analytics = load_json('data/analytics/performance.json') or {}
        state = load_json(self.state_file) or {}
        
        # Analyze by template
        template_performance = {}
        for vid, entries in analytics.items():
            if not entries:
                continue
            # Get template from DNA database
            template = self._get_video_template(vid)
            if not template:
                continue
                
            score = entries[-1]['score']
            if template not in template_performance:
                template_performance[template] = []
            template_performance[template].append(score)
            
        # Calculate averages
        template_scores = {
            t: sum(scores)/len(scores) 
            for t, scores in template_performance.items()
        }
        
        # Update probabilities
        new_weights = {}
        total = sum(template_scores.values()) if template_scores else 1
        
        for template in self.config['templates']:
            score = template_scores.get(template, 0.5)
            # Normalize to probability
            prob = score / total if total > 0 else 1/len(self.config['templates'])
            # Ensure minimum 5% chance
            prob = max(prob, 0.05)
            new_weights[template] = prob
            
        # Normalize to sum 1
        total_prob = sum(new_weights.values())
        new_weights = {k: v/total_prob for k, v in new_weights.items()}
        
        state['template_weights'] = new_weights
        state['last_evolution'] = datetime.now().isoformat()
        save_json(self.state_file, state)
        
        logger.info(f"🧬 Evolution complete. New weights: {new_weights}")
        
    def apply_behavioral_drift(self):
        """Weekly parameter drift"""
        state = load_json(self.state_file) or {}
        
        # Slightly adjust baseline parameters
        current_speed = state.get('baseline_speed', 1.0)
        current_length = state.get('baseline_length', 20)
        
        # Random walk ±2% speed, ±1.2s length
        new_speed = current_speed * random.uniform(0.98, 1.02)
        new_length = current_length + random.uniform(-1.2, 1.2)
        
        state['baseline_speed'] = round(new_speed, 3)
        state['baseline_length'] = round(new_length, 1)
        
        # Drift voice preference
        if random.random() < 0.3:  # 30% chance to shift voice bias
            current_female = self.config['voice_profiles']['female']['probability']
            shift = random.uniform(-0.05, 0.05)
            new_female = max(0.2, min(0.8, current_female + shift))
            state['voice_female_prob'] = new_female
            
        save_json(self.state_file, state)
        
    def _get_video_template(self, video_id: str) -> str:
        """Lookup template from DNA database"""
        dna = load_json('data/content_memory/dna_database.json') or []
        for entry in dna:
            # This is simplified; would need proper video ID tracking
            pass
        return random.choice(self.config['templates'])  # Fallback
