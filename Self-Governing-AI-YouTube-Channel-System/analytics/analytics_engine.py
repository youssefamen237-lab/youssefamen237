import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from database.db import get_recent_videos

# Analytics Engine for YouTube Channel Performance

class AnalyticsEngine:
    def __init__(self):
        self.data = None
        
    def load_video_data(self, limit=50):
        """
        Load recent video data from database
        
        Args:
            limit (int): Maximum number of videos to load
        
        Returns:
            list: List of video records
        """
        videos = get_recent_videos(limit)
        self.data = videos
        return videos
    
    def calculate_performance_metrics(self):
        """
        Calculate overall performance metrics
        
        Returns:
            dict: Performance metrics
        """
        if not self.data:
            self.load_video_data()
            
        if not self.data:
            return {}
        
        # Convert to DataFrame for easier analysis
        df = pd.DataFrame(self.data, columns=['id', 'title', 'description', 'thumbnail', 'views', 'watch_time', 'ctr', 'retention'])
        
        # Calculate basic metrics
        total_videos = len(df)
        total_views = df['views'].sum()
        avg_views = df['views'].mean()
        avg_watch_time = df['watch_time'].mean()
        avg_ctr = df['ctr'].mean()
        avg_retention = df['retention'].mean()
        
        # Calculate engagement rate
        engagement_rate = (avg_ctr * 100) if avg_views > 0 else 0
        
        # Calculate performance score (simplified formula)
        performance_score = (avg_views * 0.3 + avg_watch_time * 0.2 + avg_retention * 50 + avg_ctr * 1000) / 1000
        
        return {
            'total_videos': total_videos,
            'total_views': total_views,
            'average_views': round(avg_views, 2),
            'average_watch_time': round(avg_watch_time, 2),
            'average_ctr': round(avg_ctr, 4),
            'average_retention': round(avg_retention, 4),
            'engagement_rate': round(engagement_rate, 2),
            'performance_score': round(performance_score, 2)
        }
    
    def identify_best_performers(self, top_n=5):
        """
        Identify best performing videos
        
        Args:
            top_n (int): Number of top performers to return
        
        Returns:
            list: Top performing videos
        """
        if not self.data:
            self.load_video_data()
            
        if not self.data:
            return []
        
        # Convert to DataFrame
        df = pd.DataFrame(self.data, columns=['id', 'title', 'description', 'thumbnail', 'views', 'watch_time', 'ctr', 'retention'])
        
        # Sort by views (most popular)
        top_videos = df.nlargest(top_n, 'views')
        
        # Convert back to list of dictionaries
        return top_videos.to_dict('records')
    
    def analyze_trends(self):
        """
        Analyze performance trends
        
        Returns:
            dict: Trend analysis results
        """
        if not self.data:
            self.load_video_data()
            
        if not self.data:
            return {}
        
        # Convert to DataFrame
        df = pd.DataFrame(self.data, columns=['id', 'title', 'description', 'thumbnail', 'views', 'watch_time', 'ctr', 'retention'])
        
        # Calculate correlation matrix
        correlations = df[['views', 'watch_time', 'ctr', 'retention']].corr()
        
        # Calculate average performance over time (simplified)
        avg_performance = {
            'avg_views': df['views'].mean(),
            'avg_watch_time': df['watch_time'].mean(),
            'avg_ctr': df['ctr'].mean(),
            'avg_retention': df['retention'].mean()
        }
        
        return {
            'correlations': correlations.to_dict(),
            'average_performance': avg_performance
        }
    
    def generate_insights(self):
        """
        Generate actionable insights
        
        Returns:
            dict: Actionable insights
        """
        metrics = self.calculate_performance_metrics()
        trends = self.analyze_trends()
        
        insights = []
        
        # Insight 1: Engagement rate
        if metrics.get('engagement_rate', 0) > 5:
            insights.append("Excellent engagement rate - consider increasing content frequency")
        elif metrics.get('engagement_rate', 0) < 1:
            insights.append("Low engagement rate - review content quality and targeting")
        
        # Insight 2: Average views
        avg_views = metrics.get('average_views', 0)
        if avg_views > 1000:
            insights.append("High average views - content is resonating well with audience")
        elif avg_views < 100:
            insights.append("Low average views - consider optimizing titles and thumbnails")
        
        # Insight 3: Retention rate
        avg_retention = metrics.get('average_retention', 0)
        if avg_retention > 0.7:
            insights.append("High viewer retention - content is engaging")
        elif avg_retention < 0.3:
            insights.append("Low retention - consider improving content structure or pacing")
        
        # Insight 4: CTR
        avg_ctr = metrics.get('average_ctr', 0)
        if avg_ctr > 0.05:
            insights.append("Strong click-through rate - good title and thumbnail optimization")
        elif avg_ctr < 0.01:
            insights.append("Low click-through rate - review title and thumbnail strategies")
        
        return {
            'metrics': metrics,
            'trends': trends,
            'insights': insights
        }

# Global analytics instance
analytics = AnalyticsEngine()

def load_video_data(limit=50):
    """Load video data for analysis"""
    return analytics.load_video_data(limit)

def calculate_performance_metrics():
    """Calculate overall performance metrics"""
    return analytics.calculate_performance_metrics()

def identify_best_performers(top_n=5):
    """Identify best performing videos"""
    return analytics.identify_best_performers(top_n)

def analyze_trends():
    """Analyze performance trends"""
    return analytics.analyze_trends()

def generate_insights():
    """Generate actionable insights"""
    return analytics.generate_insights()

# Test the analytics engine
if __name__ == '__main__':
    print("Testing Analytics Engine...")
    
    # Test loading data
    data = load_video_data(10)
    print(f"Loaded {len(data)} videos")
    
    # Test metrics calculation
    metrics = calculate_performance_metrics()
    print(f"Performance Metrics: {metrics}")
    
    # Test insights generation
    insights = generate_insights()
    print(f"Generated Insights: {insights['insights']}")
