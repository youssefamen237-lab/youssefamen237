import os
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List
import numpy as np

try:
    from sentence_transformers import SentenceTransformer
    EMBEDDINGS_AVAILABLE = True
except:
    EMBEDDINGS_AVAILABLE = False

from utils import logger, load_json, save_json

class DnaTracker:
    def __init__(self):
        self.memory_file = 'data/content_memory/dna_database.json'
        self.recent_questions = self._load_recent(15)  # 15 days
        
        if EMBEDDINGS_AVAILABLE:
            try:
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
            except:
                self.model = None
        else:
            self.model = None
            
    def is_duplicate(self, content: Dict) -> bool:
        """Check for duplicates via hash and semantic similarity"""
        # Hash check
        current_hash = content['content_hash']
        for entry in self.recent_questions:
            if entry['hash'] == current_hash:
                logger.warning(f"Exact hash match found: {current_hash}")
                return True
                
            # Semantic similarity check
            if self.model and self._semantic_similarity(content['question'], entry['question']) > 0.65:
                logger.warning("Semantic duplicate detected")
                return True
                
        return False
    
    def _semantic_similarity(self, text1: str, text2: str) -> float:
        """Calculate semantic similarity"""
        if not self.model:
            return 0.0
            
        try:
            emb1 = self.model.encode([text1])[0]
            emb2 = self.model.encode([text2])[0]
            
            cosine_sim = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
            return float(cosine_sim)
        except:
            return 0.0
    
    def register_content(self, content: Dict, video_params: Dict):
        """Save to DNA database"""
        entry = {
            'hash': content['content_hash'],
            'question': content['question'],
            'template': content['template'],
            'timestamp': datetime.now().isoformat(),
            'video_params': video_params
        }
        
        database = load_json(self.memory_file) or []
        database.append(entry)
        
        # Keep only last 90 days
        cutoff = datetime.now() - timedelta(days=90)
        database = [e for e in database if datetime.fromisoformat(e['timestamp']) > cutoff]
        
        save_json(self.memory_file, database)
        
    def _load_recent(self, days: int) -> List[Dict]:
        """Load content from last N days"""
        if not os.path.exists(self.memory_file):
            return []
            
        database = load_json(self.memory_file) or []
        cutoff = datetime.now() - timedelta(days=days)
        return [e for e in database if datetime.fromisoformat(e['timestamp']) > cutoff]
