"""
Smart Shorts YouTube Channel Automation System
A self-governing growth engine for YouTube Shorts production

This package provides a complete automation system for producing and publishing
YouTube Shorts with intelligent analytics, content optimization, and strategy
evolution.

Main Features:
- Autonomous YouTube Shorts production
- Content diversity and anti-repetition system
- Performance tracking and attribution  
- Self-evolving strategy based on metrics
- AI-powered content generation and safety checking
- Shadow ban detection and protection
- Behavioral drift for human-like patterns
- Trend injection system

Modules:
- brain.py: Main orchestration engine
- database.py: SQLite database management
- youtube_api.py: YouTube Data API wrapper
- content_generator.py: Content and question generation
- video_engine.py: Video production and editing
- upload_scheduler.py: Upload scheduling and analytics
- content_safety.py: Safety checking and optimization
- analytics.py: Performance analysis
- report_generator.py: Report generation

Example:
    from src.brain import SmartShortsEngine
    
    engine = SmartShortsEngine()
    engine.run_daily_cycle()

"""

__version__ = "2.0.0"
__title__ = "Smart Shorts YouTube Automation Engine"
__author__ = "Smart Shorts Team"
__license__ = "MIT"

import logging
import sys

# Setup logging
log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

# Version info
VERSION_INFO = (2, 0, 0)

# Public API
__all__ = [
    'DatabaseManager',
    'YouTubeManager',
    'ContentGenerator',
    'VideoEngine',
    'UploadScheduler',
    'PerformanceAnalyzer',
    'ContentSafetyChecker',
    'SmartShortsEngine'
]
