import os
import json
from datetime import datetime, timedelta
from typing import Dict, List
from googleapiclient.discovery import build

from utils import load_json, save_json, logger

class AnalyticsEngine:
    def __init__(self, config: Dict):
        self.config = config
        self.youtube = build('youtube', 'v3', 
                           developerKey=os.getenv('YOUTUBE_API_KEY'))
        self.analytics_file = 'data/analytics/performance.json'
        
    def collect_latest_metrics(self):
        """Fetch metrics for recent uploads"""
        channel_id = os.getenv('YT_CHANNEL_ID')
        
        # Get recent videos
        response = self.youtube.search().list(
            part='snippet',
            channelId=channel_id,
            maxResults=50,
            order='date',
            type='video'
        ).execute()
        
        video_ids = [item['id']['videoId'] for item in response['items']]
        
        # Get statistics
        stats_response = self.youtube.videos().list(
            part='statistics,contentDetails',
            id=','.join(video_ids)
        ).execute()
        
        analytics_data = load_json(self.analytics_file) or {}
        
        for video in stats_response['items']:
            vid = video['id']
            stats = video['statistics']
            
            # Calculate score
            score = self._calculate_score(stats)
            
            entry = {
                'timestamp': datetime.now().isoformat(),
                'views': int(stats.get('viewCount', 0)),
                'likes': int(stats.get('likeCount', 0)),
                'comments': int(stats.get('commentCount', 0)),
                'score': score
            }
            
            if vid not in analytics_data:
                analytics_data[vid] = []
            analytics_data[vid].append(entry)
            
        save_json(self.analytics_file, analytics_data)
        
    def _calculate_score(self, stats: Dict) -> float:
        """Weighted performance score"""
        weights = self.config['strategy_weights']
        
        # Approximate metrics (YouTube Analytics API needed for precise watch time)
        views = int(stats.get('viewCount', 0))
        likes = int(stats.get('likeCount', 0))
        comments = int(stats.get('commentCount', 0))
        
        # Normalize (simple approximation)
        ctr = min(likes / max(views, 1) * 10, 1.0)  # Approximate
        engagement = (likes + comments) / max(views, 1)
        
        score = (
            weights['ctr'] * ctr +
            weights['comments'] * min(engagement * 10, 1.0)
        )
        return round(score, 3)
    
    def detect_shadow_ban(self) -> bool:
        """Detect sudden impression drops"""
        data = load_json(self.analytics_file) or {}
        if len(data) < 5:
            return False
            
        recent_scores = []
        for vid, entries in list(data.items())[-5:]:
            if entries:
                recent_scores.append(entries[-1]['score'])
                
        if not recent_scores:
            return False
            
        avg_score = sum(recent_scores) / len(recent_scores)
        threshold = self.config['thresholds']['shadow_ban_impression_drop']
        
        # If recent average is 60% lower than historical, likely shadow banned
        historical = self._get_historical_average(data)
        if historical > 0 and avg_score < historical * (1 - threshold):
            logger.warning(f"Shadow ban suspected: {avg_score} vs {historical}")
            return True
            
        return False
    
    def _get_historical_average(self, data: Dict) -> float:
        """Calculate historical baseline"""
        all_scores = []
        for vid, entries in list(data.items())[:-10]:  # Exclude last 10
            for e in entries:
                all_scores.append(e['score'])
        return sum(all_scores) / len(all_scores) if all_scores else 0
    
    def get_recent_performance(self, hours: int) -> Dict:
        """Get performance summary for last N hours"""
        # Implementation depends on detailed analytics access
        return {'avg_ctr': 0.05}  # Placeholder
