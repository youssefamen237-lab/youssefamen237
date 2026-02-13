#!/usr/bin/env python3
import os
import sys
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any

sys.path.insert(0, '/workspaces/youssefamen237/src')

from database import DatabaseManager
from youtube_api import YouTubeManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ReportGenerator:
    def __init__(self):
        self.db = DatabaseManager()
        self.youtube = YouTubeManager()

    def generate_daily_report(self) -> Dict[str, Any]:
        """Generate daily performance report"""
        try:
            logger.info("📋 Generating daily report...")
            
            today = datetime.now().date()
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Get today's uploads
            cursor.execute('''SELECT COUNT(*) as count FROM upload_history 
                           WHERE DATE(upload_timestamp) = ? AND upload_succeeded = 1''', 
                          (today,))
            today_uploads = cursor.fetchone()['count']
            
            # Get today's performance
            cursor.execute('''SELECT 
                            AVG(performance_score) as avg_score,
                            MAX(performance_score) as max_score,
                            MIN(performance_score) as min_score,
                            AVG(ctr) as avg_ctr,
                            AVG(completion_rate) as avg_completion
                         FROM video_performance 
                         WHERE DATE(upload_time) = ?''', (today,))
            
            today_perf = cursor.fetchone()
            
            # Get week stats
            cursor.execute('''SELECT COUNT(*) as count FROM upload_history 
                           WHERE upload_timestamp > datetime('now', '-7 days')
                           AND upload_succeeded = 1''')
            week_uploads = cursor.fetchone()['count']
            
            # Get month stats
            cursor.execute('''SELECT COUNT(*) as count FROM upload_history 
                           WHERE upload_timestamp > datetime('now', '-30 days')
                           AND upload_succeeded = 1''')
            month_uploads = cursor.fetchone()['count']
            
            # Get channel stats
            channel_stats = self.youtube.get_channel_analytics()
            
            conn.close()
            
            import sys
                    'avg_ctr': round(today_perf['avg_ctr'] or 0, 2),
                    'avg_completion': round(today_perf['avg_completion'] or 0, 2)
                },
                'weekly': {
                    'uploads': week_uploads,
                    'avg_per_day': round(week_uploads / 7, 1)
                },
                'monthly': {
                    'uploads': month_uploads,
                    'avg_per_day': round(month_uploads / 30, 1)
                },
                'channel': {
                    'subscribers': channel_stats.get('subscriber_count', 0) if channel_stats else 0,
                    'total_views': channel_stats.get('view_count', 0) if channel_stats else 0,
                    'total_videos': channel_stats.get('video_count', 0) if channel_stats else 0
                }
            }
            
            return report

        except Exception as e:
            logger.error(f"Error generating daily report: {e}")
            return {}

    def generate_weekly_report(self) -> Dict[str, Any]:
        """Generate weekly performance report and create long-form content"""
        try:
            logger.info("📊 Generating weekly report...")
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Get top 10 videos from week
            cursor.execute('''SELECT video_id, question_type, performance_score, 
                            ctr, completion_rate, comments_count
                         FROM video_performance 
                         WHERE upload_time > datetime('now', '-7 days')
                         ORDER BY performance_score DESC
                         LIMIT 10''')
            
            top_videos = cursor.fetchall()
            
            # Get performance by type
            cursor.execute('''SELECT question_type, 
                            AVG(performance_score) as avg_score,
                            COUNT(*) as count,
                            AVG(ctr) as avg_ctr
                         FROM video_performance 
                         WHERE upload_time > datetime('now', '-7 days')
                         GROUP BY question_type
                         ORDER BY avg_score DESC''')
            
            type_performance = cursor.fetchall()
            
            # Get insights
            cursor.execute('''SELECT 
                            AVG(performance_score) as avg_score,
                            AVG(completion_rate) as avg_completion
                         FROM video_performance 
                         WHERE upload_time > datetime('now', '-7 days')''')
            
            insights = cursor.fetchone()
            
            conn.close()
            
            week_start = (datetime.now() - timedelta(days=7)).date()
            week_end = datetime.now().date()
            
            report = {
                'period': f"{week_start} to {week_end}",
                'top_videos': [
                    {
                        'video_id': dict(v)['video_id'],
                        'type': dict(v)['question_type'],
                        'score': round(dict(v)['performance_score'], 3),
                        'ctr': round(dict(v)['ctr'] or 0, 2),
                        'completion': round(dict(v)['completion_rate'] or 0, 2)
                    }
                    for v in top_videos
                ],
                'performance_by_type': [
                    {
                        'type': dict(t)['question_type'],
                        'avg_score': round(dict(t)['avg_score'] or 0, 3),
                        'count': dict(t)['count'],
                        'avg_ctr': round(dict(t)['avg_ctr'] or 0, 2)
                    }
                    for t in type_performance
                ],
                'overall_insights': {
                    'avg_performance': round(insights['avg_score'] or 0, 3),
                    'avg_completion': round(insights['avg_completion'] or 0, 2)
                },
                'recommendations': self._generate_weekly_recommendations(insights)
            }
            
            logger.info("✅ Weekly report generated")
            
            return report

        except Exception as e:
            logger.error(f"Error generating weekly report: {e}")
            return {}

    def _generate_weekly_recommendations(self, insights: Dict) -> list:
        """Generate recommendations based on weekly data"""
        recommendations = []
        
        avg_score = insights.get('avg_score', 0)
        avg_completion = insights.get('avg_completion', 0)
        
        if avg_score > 0.8:
            recommendations.append("Excellent week! Continue with current strategy")
        elif avg_score > 0.6:
            recommendations.append("Good performance. Focus on consistency")
        else:
            recommendations.append("Consider testing new content formats")
        
        if avg_completion > 80:
            recommendations.append("High retention - videos resonate well")
        elif avg_completion < 50:
            recommendations.append("Improve hooks - viewers dropping early")
        
        return recommendations

    def generate_financial_report(self) -> Dict[str, Any]:
        """Generate estimated financial metrics"""
        try:
            logger.info("💰 Generating financial report...")
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Get recent stats
            cursor.execute('''SELECT COUNT(*) as videos, 
                            SUM(impressions) as total_impressions,
                            AVG(ctr) as avg_ctr
                         FROM video_performance 
                         WHERE upload_time > datetime('now', '-30 days')''')
            
            monthly_stats = cursor.fetchone()
            
            conn.close()
            
            # Rough estimates (CPM varies wildly)
            total_impressions = monthly_stats['total_impressions'] or 0
            avg_ctr = monthly_stats['avg_ctr'] or 0
            
            # Estimated clicks
            estimated_clicks = (total_impressions / 100) * avg_ctr
            
            # Assume $5 CPM average
            estimated_revenue = (total_impressions / 1000) * 5
            
            report = {
                'period': 'Last 30 days',
                'metrics': {
                    'total_impressions': int(total_impressions),
                    'estimated_ctr': round(avg_ctr, 2),
                    'estimated_clicks': int(estimated_clicks),
                    'estimated_revenue': round(estimated_revenue, 2),
                    'videos_count': monthly_stats['videos'] or 0
                },
                'notes': [
                    'Revenue estimates are rough (actual CPM varies by region)',
                    'YouTube takes 45%, you receive 55%',
                    'Estimates based on $5 average CPM'
                ]
            }
            
            return report

        except Exception as e:
            logger.error(f"Error generating financial report: {e}")
            return {}

    def save_reports(self, daily: Dict, weekly: Dict = None, financial: Dict = None):
        """Save reports to JSON files"""
        try:
            log_dir = '/workspaces/youssefamen237/logs'
            os.makedirs(log_dir, exist_ok=True)
            
            # Daily report
            daily_file = os.path.join(log_dir, f"daily_report_{datetime.now().strftime('%Y%m%d')}.json")
            with open(daily_file, 'w') as f:
                json.dump(daily, f, indent=2)
            logger.info(f"Daily report saved: {daily_file}")
            
            # Weekly report
            if weekly:
                weekly_file = os.path.join(log_dir, f"weekly_report_{datetime.now().strftime('%Y_W%W')}.json")
                with open(weekly_file, 'w') as f:
                    json.dump(weekly, f, indent=2)
                logger.info(f"Weekly report saved: {weekly_file}")
            
            # Financial report
            if financial:
                financial_file = os.path.join(log_dir, f"financial_report_{datetime.now().strftime('%Y%m')}.json")
                with open(financial_file, 'w') as f:
                    json.dump(financial, f, indent=2)
                logger.info(f"Financial report saved: {financial_file}")

        except Exception as e:
            logger.error(f"Error saving reports: {e}")

def main():
    """Generate and save all reports"""
    try:
        generator = ReportGenerator()
        
        daily = generator.generate_daily_report()
        weekly = generator.generate_weekly_report()
        financial = generator.generate_financial_report()
        
        generator.save_reports(daily, weekly, financial)
        
        logger.info("✅ All reports generated successfully!")

    except Exception as e:
        logger.error(f"Error in report generation: {e}", exc_info=True)

if __name__ == "__main__":
    main()
