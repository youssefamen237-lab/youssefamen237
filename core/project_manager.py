import os
import json
import time
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

class ProjectManager:
    def __init__(self):
        self.setup_logger()
        self.setup_youtube_analytics()
        self.performance_data = self.load_performance_data()
        self.optimization_rules = self.load_optimization_rules()
        self.last_analysis_time = None
        self.analysis_interval = timedelta(hours=6)  # Analyze every 6 hours
        
    def setup_logger(self):
        self.logger = logging.getLogger('ProjectManager')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('logs/system.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def setup_youtube_analytics(self):
        """Setup YouTube Analytics API connection"""
        try:
            client_id = os.getenv('YT_CLIENT_ID_3')
            client_secret = os.getenv('YT_CLIENT_SECRET_3')
            refresh_token = os.getenv('YT_REFRESH_TOKEN_3')
            
            if not all([client_id, client_secret, refresh_token]):
                self.logger.error("Missing YouTube API credentials for analytics")
                self.youtube_analytics = None
                return
                
            credentials = Credentials(
                None,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
                token_uri='https://oauth2.googleapis.com/token'
            )
            
            self.youtube_analytics = build('youtubeAnalytics', 'v2', credentials=credentials)
            self.logger.info("YouTube Analytics API connected successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to setup YouTube Analytics: {str(e)}")
            self.youtube_analytics = None
    
    def load_performance_data(self) -> Dict:
        """Load existing performance data or initialize new"""
        try:
            if os.path.exists('data/performance_data.json'):
                with open('data/performance_data.json', 'r') as f:
                    return json.load(f)
        except:
            pass
            
        # Initialize with default structure
        return {
            "videos": [],
            "shorts": [],
            "overall_metrics": {
                "total_views": 0,
                "average_watch_time": 0,
                "subscriber_growth": 0,
                "best_performing_template": "",
                "best_publishing_time": ""
            },
            "template_performance": {},
            "publishing_time_performance": {}
        }
    
    def save_performance_data(self):
        """Save current performance data to disk"""
        try:
            with open('data/performance_data.json', 'w') as f:
                json.dump(self.performance_data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save performance data: {str(e)}")
    
    def load_optimization_rules(self) -> Dict:
        """Load optimization rules from file or initialize defaults"""
        try:
            if os.path.exists('config/optimization_rules.json'):
                with open('config/optimization_rules.json', 'r') as f:
                    return json.load(f)
        except:
            pass
            
        # Default optimization rules
        return {
            "template_selection": {
                "weight": 0.35,
                "rules": [
                    {"condition": "views > 1000", "weight_adjustment": 0.1},
                    {"condition": "rewatch_rate > 0.3", "weight_adjustment": 0.15},
                    {"condition": "comment_rate > 0.05", "weight_adjustment": 0.05}
                ]
            },
            "publishing_time": {
                "weight": 0.25,
                "rules": [
                    {"condition": "peak_viewers > 500", "weight_adjustment": 0.1},
                    {"condition": "subscriber_growth > 0.01", "weight_adjustment": 0.05}
                ]
            },
            "thumbnail_style": {
                "weight": 0.2,
                "rules": [
                    {"condition": "ctr > 0.08", "weight_adjustment": 0.1}
                ]
            },
            "content_length": {
                "weight": 0.2,
                "rules": [
                    {"condition": "average_watch_time > 0.8", "weight_adjustment": 0.1},
                    {"condition": "drop_off < 0.3", "weight_adjustment": 0.05}
                ]
            }
        }
    
    def should_analyze(self) -> bool:
        """Determine if it's time to run analysis"""
        if self.last_analysis_time is None:
            return True
            
        return datetime.now() - self.last_analysis_time > self.analysis_interval
    
    def analyze_performance(self):
        """Analyze channel performance and update optimization strategies"""
        if not self.youtube_analytics:
            self.logger.warning("Cannot analyze performance: YouTube Analytics not connected")
            return False
            
        try:
            # Fetch latest analytics data
            shorts_data = self._fetch_shorts_analytics()
            long_video_data = self._fetch_long_video_analytics()
            
            # Update performance database
            self._update_performance_database(shorts_data, long_video_data)
            
            # Generate optimization insights
            self._generate_optimization_insights()
            
            # Save updated data
            self.save_performance_data()
            
            self.last_analysis_time = datetime.now()
            self.logger.info("Performance analysis completed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error during performance analysis: {str(e)}")
            return False
    
    def _fetch_shorts_analytics(self) -> List[Dict]:
        """Fetch analytics data for Shorts videos"""
        try:
            # In a real implementation, this would query the YouTube Analytics API
            # This is a simplified placeholder
            
            # Get list of Shorts videos
            shorts_list = self._get_shorts_list()
            
            analytics_data = []
            for short in shorts_list:
                # Would fetch actual analytics in production
                analytics_data.append({
                    "video_id": short["id"],
                    "title": short["title"],
                    "publish_time": short["publishedAt"],
                    "views": random.randint(100, 10000),
                    "watch_time": random.uniform(0.5, 0.95),
                    "rewatch_rate": random.uniform(0.1, 0.4),
                    "comment_rate": random.uniform(0.01, 0.1),
                    "shares": random.randint(0, 500),
                    "likes": random.randint(0, 2000),
                    "template": self._get_template_from_title(short["title"]),
                    "publish_hour": int(short["publishedAt"][11:13])
                })
                
            return analytics_data
            
        except Exception as e:
            self.logger.error(f"Error fetching Shorts analytics: {str(e)}")
            return []
    
    def _fetch_long_video_analytics(self) -> List[Dict]:
        """Fetch analytics data for long-form videos"""
        try:
            # Similar to _fetch_shorts_analytics but for long videos
            # Implementation would be parallel
            
            return []
            
        except Exception as e:
            self.logger.error(f"Error fetching long video analytics: {str(e)}")
            return []
    
    def _get_shorts_list(self) -> List[Dict]:
        """Get list of Shorts videos from YouTube"""
        try:
            # In production, this would query YouTube Data API
            # This is a placeholder
            
            # Would normally fetch from YouTube API
            return [
                {"id": f"short_{i}", "title": f"Short #{i}", "publishedAt": self._generate_random_time()}
                for i in range(1, 21)
            ]
            
        except Exception as e:
            self.logger.error(f"Error getting Shorts list: {str(e)}")
            return []
    
    def _generate_random_time(self) -> str:
        """Generate a random time in ISO format for testing"""
        days_ago = random.randint(0, 30)
        hours = random.randint(0, 23)
        minutes = random.randint(0, 59)
        seconds = random.randint(0, 59)
        
        now = datetime.now() - timedelta(days=days_ago, hours=hours, minutes=minutes, seconds=seconds)
        return now.isoformat() + "Z"
    
    def _get_template_from_title(self, title: str) -> str:
        """Extract template type from video title"""
        template_keywords = {
            "true_false": ["true or false", "fact check"],
            "multiple_choice": ["quiz", "which one", "choose"],
            "direct_question": ["question", "did you know"],
            "guess_answer": ["guess", "what is"],
            "quick_challenge": ["challenge", "can you"],
            "only_geniuses": ["genius", "smart"],
            "memory_test": ["remember", "recall"],
            "visual_question": ["image", "picture"]
        }
        
        title_lower = title.lower()
        for template, keywords in template_keywords.items():
            if any(keyword in title_lower for keyword in keywords):
                return template
                
        return "direct_question"  # Default template
    
    def _update_performance_database(self, shorts_data: List[Dict], long_video_data: List[Dict]):
        """Update the performance database with new analytics"""
        # Update Shorts performance
        for short in shorts_data:
            # Check if we already have data for this short
            existing = next((s for s in self.performance_data["shorts"] 
                           if s["video_id"] == short["video_id"]), None)
            
            if existing:
                # Update existing record
                existing.update(short)
            else:
                # Add new record
                self.performance_data["shorts"].append(short)
        
        # Update long video performance (similar logic)
        # ...
        
        # Update overall metrics
        self._update_overall_metrics()
    
    def _update_overall_metrics(self):
        """Update overall channel metrics based on current data"""
        shorts = self.performance_data["shorts"]
        
        if shorts:
            self.performance_data["overall_metrics"]["total_views"] = sum(s["views"] for s in shorts)
            self.performance_data["overall_metrics"]["average_watch_time"] = sum(s["watch_time"] for s in shorts) / len(shorts)
            
            # Find best performing template
            template_views = {}
            for short in shorts:
                template = short["template"]
                template_views[template] = template_views.get(template, 0) + short["views"]
            
            if template_views:
                best_template = max(template_views.items(), key=lambda x: x[1])[0]
                self.performance_data["overall_metrics"]["best_performing_template"] = best_template
                
            # Find best publishing time
            hour_views = {}
            for short in shorts:
                hour = short["publish_hour"]
                hour_views[hour] = hour_views.get(hour, 0) + short["views"]
            
            if hour_views:
                best_hour = max(hour_views.items(), key=lambda x: x[1])[0]
                self.performance_data["overall_metrics"]["best_publishing_time"] = f"{best_hour}:00"
    
    def _generate_optimization_insights(self):
        """Generate insights to optimize future content"""
        # Analyze template performance
        self._analyze_template_performance()
        
        # Analyze publishing time performance
        self._analyze_publishing_time()
        
        # Analyze thumbnail effectiveness
        self._analyze_thumbnail_performance()
        
        # Analyze content length effectiveness
        self._analyze_content_length()
        
        # Save updated optimization rules
        self._save_optimization_rules()
    
    def _analyze_template_performance(self):
        """Analyze which templates perform best"""
        shorts = self.performance_data["shorts"]
        if not shorts:
            return
            
        # Group by template
        template_data = {}
        for short in shorts:
            template = short["template"]
            if template not in template_data:
                template_data[template] = {
                    "count": 0,
                    "total_views": 0,
                    "total_watch_time": 0,
                    "total_comments": 0,
                    "total_shares": 0
                }
                
            template_data[template]["count"] += 1
            template_data[template]["total_views"] += short["views"]
            template_data[template]["total_watch_time"] += short["watch_time"]
            template_data[template]["total_comments"] += short.get("comments", 0)
            template_data[template]["total_shares"] += short.get("shares", 0)
        
        # Calculate averages
        for template, data in template_data.items():
            count = data["count"]
            template_data[template]["avg_views"] = data["total_views"] / count
            template_data[template]["avg_watch_time"] = data["total_watch_time"] / count
            template_data[template]["comment_rate"] = data["total_comments"] / data["total_views"] if data["total_views"] > 0 else 0
            template_data[template]["share_rate"] = data["total_shares"] / data["total_views"] if data["total_views"] > 0 else 0
        
        # Determine performance scores
        for template, data in template_data.items():
            # Simple scoring formula (would be more sophisticated in production)
            score = (
                (data["avg_views"] / 1000) * 0.4 +  # Normalize views
                data["avg_watch_time"] * 0.3 +
                data["comment_rate"] * 100 * 0.2 +
                data["share_rate"] * 100 * 0.1
            )
            template_data[template]["performance_score"] = score
        
        # Update template performance in main data
        self.performance_data["template_performance"] = template_data
    
    def _analyze_publishing_time(self):
        """Analyze which publishing times perform best"""
        shorts = self.performance_data["shorts"]
        if not shorts:
            return
            
        # Group by hour
        hour_data = {}
        for short in shorts:
            hour = short["publish_hour"]
            if hour not in hour_data:
                hour_data[hour] = {
                    "count": 0,
                    "total_views": 0,
                    "total_subscribers": 0
                }
                
            hour_data[hour]["count"] += 1
            hour_data[hour]["total_views"] += short["views"]
            # Would track subscribers in production
            
        # Calculate averages
        for hour, data in hour_data.items():
            hour_data[hour]["avg_views"] = data["total_views"] / data["count"]
            hour_data[hour]["subscriber_growth"] = data["total_subscribers"] / data["count"] if data["count"] > 0 else 0
        
        # Determine best times
        self.performance_data["publishing_time_performance"] = hour_data
    
    def _analyze_thumbnail_performance(self):
        """Analyze which thumbnail styles perform best"""
        # Would implement similar to template analysis
        pass
    
    def _analyze_content_length(self):
        """Analyze optimal content length"""
        # Would implement similar to template analysis
        pass
    
    def _save_optimization_rules(self):
        """Save updated optimization rules based on analysis"""
        # Update template selection weights based on performance
        if self.performance_data["template_performance"]:
            best_template = max(
                self.performance_data["template_performance"].items(),
                key=lambda x: x[1]["performance_score"]
            )[0]
            
            # Adjust rules to favor best performing template
            self.optimization_rules["template_selection"]["rules"].append({
                "condition": f"template == '{best_template}'",
                "weight_adjustment": 0.05
            })
            
            # Save updated rules
            with open('config/optimization_rules.json', 'w') as f:
                json.dump(self.optimization_rules, f, indent=2)
    
    def get_optimized_parameters(self) -> Dict:
        """Get optimized parameters for content generation"""
        if not self.should_analyze():
            # Return previously calculated parameters
            return self._load_cached_parameters()
        
        # Run analysis if needed
        self.analyze_performance()
        
        # Generate optimized parameters
        params = {
            "preferred_template": self._get_best_template(),
            "optimal_publish_time": self._get_best_publish_time(),
            "preferred_thumbnail_style": self._get_best_thumbnail_style(),
            "optimal_content_length": self._get_optimal_content_length()
        }
        
        # Cache the parameters
        self._cache_parameters(params)
        
        return params
    
    def _get_best_template(self) -> str:
        """Get the best performing template based on analysis"""
        if not self.performance_data["template_performance"]:
            return "direct_question"  # Default
            
        best = max(
            self.performance_data["template_performance"].items(),
            key=lambda x: x[1]["performance_score"]
        )
        return best[0]
    
    def _get_best_publish_time(self) -> str:
        """Get the best publishing time based on analysis"""
        if not self.performance_data["publishing_time_performance"]:
            # Default to 9AM, 1PM, 4PM, 8PM
            return str(random.choice([9, 13, 16, 20]))
            
        best = max(
            self.performance_data["publishing_time_performance"].items(),
            key=lambda x: x[1]["avg_views"]
        )
        return str(best[0])
    
    def _get_best_thumbnail_style(self) -> str:
        """Get the best thumbnail style based on analysis"""
        # Would implement based on actual thumbnail data
        return "dynamic_text"
    
    def _get_optimal_content_length(self) -> float:
        """Get the optimal content length based on analysis"""
        # Would implement based on actual watch time data
        return 8.5  # Default for Shorts
    
    def _load_cached_parameters(self) -> Dict:
        """Load previously cached optimization parameters"""
        try:
            if os.path.exists('data/optimization_cache.json'):
                with open('data/optimization_cache.json', 'r') as f:
                    return json.load(f)
        except:
            pass
            
        # Return defaults if no cache
        return {
            "preferred_template": "direct_question",
            "optimal_publish_time": str(random.choice([9, 13, 16, 20])),
            "preferred_thumbnail_style": "dynamic_text",
            "optimal_content_length": 8.5
        }
    
    def _cache_parameters(self, params: Dict):
        """Cache optimization parameters for future use"""
        try:
            with open('data/optimization_cache.json', 'w') as f:
                json.dump(params, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to cache optimization parameters: {str(e)}")
