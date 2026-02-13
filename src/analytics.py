#!/usr/bin/env python3
import os
import sys
import logging
import json
from datetime import datetime, timedelta

sys.path.insert(0, '/workspaces/youssefamen237/src')

from database import DatabaseManager
from youtube_api import YouTubeManager
from upload_scheduler import PerformanceAnalyzer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_analytics():
    """Run analytics and generate insights"""
    try:
        logger.info("📊 Running analytics...")
        
        db = DatabaseManager()
        youtube = YouTubeManager()
        analyzer = PerformanceAnalyzer(db, youtube)
        
        # Analyze recent videos
        analysis = analyzer.analyze_recent_videos()
        
        logger.info(f"Videos analyzed: {analysis.get('videos_analyzed', 0)}")
        logger.info(f"Average performance: {analysis.get('average_performance', 0):.3f}")
        
        # Get performance trends
        trends = db.get_performance_trends(days=30)
        if trends:
            logger.info(f"Trend data points: {len(trends.get('dates', []))}")
        
        # Check shadow ban
        shadow_ban = analyzer.detect_shadow_ban()
        if shadow_ban['suspicious']:
            logger.warning(f"⚠️ ALERT: {shadow_ban['action']}")
        
        # Get analytics summary
        summary = db.get_analytics_summary()
        logger.info(f"Total videos: {summary.get('total_videos', 0)}")
        logger.info(f"Recent 7 days: {summary.get('recent_7_days', 0)} videos")
        
        # Save analytics to JSON
        analytics_data = {
            'timestamp': datetime.now().isoformat(),
            'analysis': analysis,
            'summary': summary,
            'shadow_ban': {
                'suspicious': shadow_ban.get('suspicious'),
                'action': shadow_ban.get('action'),
                'impressions_trend': shadow_ban.get('impressions_trend')
            },
            'trends': trends
        }
        
        analytics_file = '/workspaces/youssefamen237/logs/analytics.json'
        os.makedirs(os.path.dirname(analytics_file), exist_ok=True)
        
        with open(analytics_file, 'w') as f:
            json.dump(analytics_data, f, indent=2)
        
        logger.info("✅ Analytics complete!")
        
        return analytics_data

    except Exception as e:
        logger.error(f"Error in analytics: {e}", exc_info=True)
        return None

if __name__ == "__main__":
    run_analytics()
