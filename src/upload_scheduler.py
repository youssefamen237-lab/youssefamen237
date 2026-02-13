import os
import random
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import time

logger = logging.getLogger(__name__)

class UploadScheduler:
    def __init__(self, db_manager, youtube_api):
        self.db = db_manager
        self.youtube = youtube_api
        self.max_daily = 8
        self.max_weekly = 50
        self.min_retry_delay = 17 * 60  # 17 minutes
        self.max_retry_delay = 6 * 3600  # 6 hours
        
    def should_upload_now(self) -> bool:
        """Check if conditions are right for upload"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Check daily limit - fixed for SQLite compatibility
            cursor.execute('''SELECT COUNT(*) as count FROM upload_history 
                           WHERE strftime('%Y-%m-%d', upload_timestamp) = strftime('%Y-%m-%d', 'now')
                           AND upload_succeeded = 1''')
            result = cursor.fetchone()
            daily_count = result['count'] if result else 0
            
            # Check weekly limit - fixed for SQLite compatibility
            cursor.execute('''SELECT COUNT(*) as count FROM upload_history 
                           WHERE upload_timestamp > datetime('now', '-7 days')
                           AND upload_succeeded = 1''')
            result = cursor.fetchone()
            weekly_count = result['count'] if result else 0
            
            # Check shadow ban status
            cursor.execute('''SELECT is_suspicious FROM shadow_ban_detection 
                           ORDER BY check_date DESC LIMIT 1''')
            result = cursor.fetchone()
            shadow_ban_suspected = result['is_suspicious'] if result else False
            
            conn.close()
            
            logger.info(f"Upload check: daily={daily_count}/{self.max_daily}, weekly={weekly_count}/{self.max_weekly}, shadow_ban={shadow_ban_suspected}")
            
            if shadow_ban_suspected:
                logger.warning("⛔ Shadow ban suspected, pausing uploads")
                return False
            
            if daily_count >= self.max_daily:
                logger.warning(f"📊 Daily limit reached: {daily_count}/{self.max_daily}")
                return False
            
            if weekly_count >= self.max_weekly:
                logger.warning(f"📈 Weekly limit reached: {weekly_count}/{self.max_weekly}")
                return False
            
            logger.info("✅ Upload conditions met!")
            return True

        except Exception as e:
            logger.error(f"❌ Error checking upload conditions: {e}", exc_info=True)
            # On error, allow upload (fail-safe)
            logger.warning("⚠️  Allowing upload despite error in conditions check")
            return True

    def get_random_upload_delay(self) -> int:
        """Get random upload delay in seconds (2-11 minutes)"""
        return random.randint(2 * 60, 11 * 60)

    def get_optimal_upload_time(self) -> Optional[datetime]:
        """Determine optimal upload time based on analytics"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Analyze upload times and performance
            cursor.execute('''SELECT 
                            strftime('%H', upload_time) as hour,
                            AVG(performance_score) as avg_score,
                            COUNT(*) as count
                         FROM video_performance
                         WHERE upload_time > datetime('now', '-30 days')
                         GROUP BY hour
                         ORDER BY avg_score DESC
                         LIMIT 1''')
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                best_hour = int(result['hour'])
                now = datetime.now()
                optimal = now.replace(hour=best_hour, minute=random.randint(0, 59),
                                    second=random.randint(0, 59))
                
                # If time passed, schedule for next day
                if optimal < now:
                    optimal += timedelta(days=1)
                
                return optimal
            
            # Default to random time if no data
            return self._get_random_upload_time()

        except Exception as e:
            logger.error(f"Error getting optimal upload time: {e}")
            return self._get_random_upload_time()

    def _get_random_upload_time(self) -> datetime:
        """Get random upload time with variance"""
        now = datetime.now()
        
        # Random hour between 8 AM and 11 PM
        hour = random.randint(8, 23)
        minute = random.randint(0, 59)
        
        upload_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # If time passed, schedule for next day
        if upload_time < now:
            upload_time += timedelta(days=1)
        
        # Add random variance (±30 minutes)
        variance = random.randint(-30 * 60, 30 * 60)
        upload_time += timedelta(seconds=variance)
        
        return upload_time

    def calculate_optimal_upload_density(self) -> int:
        """Calculate upload frequency based on performance"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Get recent performance
            cursor.execute('''SELECT 
                            AVG(performance_score) as avg_score,
                            AVG(ctr) as avg_ctr,
                            AVG(completion_rate) as avg_completion
                         FROM video_performance
                         WHERE upload_time > datetime('now', '-3 days')''')
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                return 4  # Default 4 videos
            
            avg_score = result['avg_score'] or 0
            
            # Performance-based density
            if avg_score > 0.7:  # Excellent performance
                return 8  # +20% increase from 4
            elif avg_score > 0.6:
                return 7
            elif avg_score > 0.4:
                return 5
            elif avg_score > 0.2:
                return 3  # -30% decrease
            else:
                return 2  # Pause for 24 hours
            
        except Exception as e:
            logger.error(f"Error calculating upload density: {e}")
            return 4

    async def execute_upload(self, video_path: str, title: str, description: str,
                           tags: List[str], content_data: Dict[str, Any]) -> Optional[str]:
        """Execute upload with error handling and retry logic"""
        try:
            logger.info(f"🚀 Starting upload: {video_path}")
            logger.info(f"   Title: {title[:50]}...")
            logger.info(f"   Tags: {', '.join(tags)}")
            
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    logger.info(f"   Attempt {retry_count + 1}/{max_retries}...")
                    
                    # Verify video file exists
                    if not os.path.exists(video_path):
                        logger.error(f"❌ Video file not found: {video_path}")
                        return None
                    
                    video_id = self.youtube.upload_short(
                        video_path, title, description, tags
                    )
                    
                    if video_id:
                        logger.info(f"✅ Video uploaded successfully!")
                        logger.info(f"   Video ID: {video_id}")
                        
                        # Record successful upload
                        try:
                            self.db.record_upload(video_id, title, description,
                                                content_data.get('type'), True)
                            logger.info("✅ Upload recorded in database")
                        except Exception as e:
                            logger.warning(f"⚠️  Could not record upload: {e}")
                        
                        return video_id
                    else:
                        logger.warning(f"⚠️  Upload returned no video ID")
                        retry_count += 1
                        
                        if retry_count < max_retries:
                            delay = self.min_retry_delay + random.randint(0, 5 * 60)
                            logger.info(f"   Retrying in {delay}s ({delay/60:.1f}m)...")
                            time.sleep(delay)
                
                except Exception as e:
                    logger.error(f"❌ Upload attempt {retry_count + 1} error: {e}", exc_info=True)
                    retry_count += 1
                    
                    if retry_count < max_retries:
                        delay = self.min_retry_delay * (retry_count + 1)  # Exponential backoff
                        logger.info(f"   Retrying in {delay}s ({delay/60:.1f}m)...")
                        time.sleep(delay)
            
            # Record failed upload after max retries
            logger.error(f"❌ Upload failed after {max_retries} attempts")
            try:
                failure_reason = "Max retries exceeded"
                self.db.record_upload(
                    f"failed_{datetime.now().timestamp()}",
                    title, description, content_data.get('type'), False, failure_reason
                )
                logger.info("📋 Failure recorded in database")
            except Exception as e:
                logger.warning(f"⚠️  Could not record failure: {e}")
            
            return None

        except Exception as e:
            logger.error(f"❌ Error executing upload: {e}", exc_info=True)
            return None


class PerformanceAnalyzer:
    def __init__(self, db_manager, youtube_api):
        self.db = db_manager
        self.youtube = youtube_api

    def analyze_recent_videos(self) -> Dict[str, Any]:
        """Analyze performance of recent videos"""
        try:
            recent_videos = self.youtube.get_recent_videos(max_results=30)
            
            if not recent_videos:
                return {}
            
            analysis = {
                'videos_analyzed': 0,
                'average_performance': 0,
                'top_performing_type': None,
                'insights': [],
                'recommendations': []
            }
            
            video_scores = {}
            
            for video in recent_videos:
                video_id = video['video_id']
                analytics = self.youtube.get_video_analytics(video_id)
                
                if not analytics:
                    continue
                
                # Save performance data
                video_data = {
                    'video_id': video_id,
                    'question_type': 'Unknown',
                    'video_length': 10.0,
                    'voice_gender': 'female',
                    'background_type': 'gradient',
                    'upload_time': video['published_at'],
                    'title_format': 'Standard',
                    'cta_used': 'Default',
                    'timer_duration': 5.0,
                    'speech_speed': 1.0,
                    'watch_time': analytics.get('estimated_watch_time', 0),
                    'completion_rate': analytics.get('estimated_completion', 0),
                    'ctr': analytics.get('estimated_ctr', 0),
                    'comments_count': analytics.get('comment_count', 0),
                    'rewatch_rate': 0,
                    'impressions': analytics.get('view_count', 0)
                }
                
                self.db.save_video_performance(video_data)
                
                performance_score = self.db._calculate_performance_score(video_data)
                video_scores[video_id] = performance_score
                
                analysis['videos_analyzed'] += 1
            
            if video_scores:
                analysis['average_performance'] = sum(video_scores.values()) / len(video_scores)
                analysis['top_performing_type'] = max(video_scores, key=video_scores.get)
                
                # Generate insights
                if analysis['average_performance'] > 0.7:
                    analysis['insights'].append("Excellent performance - increase upload density")
                elif analysis['average_performance'] < 0.3:
                    analysis['insights'].append("Poor performance - consider strategy adjustment")
                
                analysis['recommendations'] = self._generate_recommendations(analysis)
            
            return analysis

        except Exception as e:
            logger.error(f"Error analyzing recent videos: {e}")
            return {}

    def _generate_recommendations(self, analysis: Dict[str, Any]) -> List[str]:
        """Generate strategy recommendations"""
        recommendations = []
        
        avg_perf = analysis.get('average_performance', 0)
        
        if avg_perf > 0.8:
            recommendations.append("Maintain current strategy - performance is excellent")
            recommendations.append("Consider testing premium content features")
        elif avg_perf > 0.6:
            recommendations.append("Focus on consistency - performance is good")
        elif avg_perf > 0.4:
            recommendations.append("Review hook effectiveness and CTAs")
            recommendations.append("Test different question types")
        else:
            recommendations.append("Major strategy adjustment needed")
            recommendations.append("Increase variety in content format")
            recommendations.append("Improve hook and initial engagement")
        
        return recommendations

    def detect_shadow_ban(self) -> Dict[str, Any]:
        """Detect potential shadow ban based on metrics"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Get recent and older performance
            cursor.execute('''SELECT 
                            COUNT(*) as recent_count,
                            AVG(impressions) as recent_impressions,
                            AVG(ctr) as recent_ctr
                         FROM video_performance
                         WHERE upload_time > datetime('now', '-3 days')''')
            
            recent = cursor.fetchone()
            
            cursor.execute('''SELECT 
                            COUNT(*) as older_count,
                            AVG(impressions) as older_impressions,
                            AVG(ctr) as older_ctr
                         FROM video_performance
                         WHERE upload_time BETWEEN datetime('now', '-10 days')
                           AND datetime('now', '-7 days')''')
            
            older = cursor.fetchone()
            conn.close()
            
            result = {
                'suspicious': False,
                'impressions_trend': 0,
                'ctr_trend': 0,
                'action': 'Continue monitoring'
            }
            
            if recent and older and older['older_count'] > 0:
                recent_imp = recent['recent_impressions'] or 0
                older_imp = older['older_impressions'] or 1
                
                # Calculate trend
                imp_change = ((recent_imp - older_imp) / older_imp) * 100
                result['impressions_trend'] = imp_change
                
                # Suspicious if 60% drop
                if imp_change < -60:
                    result['suspicious'] = True
                    result['action'] = 'Pause uploads for 48 hours'
                    logger.warning("Possible shadow ban detected! Impressions dropped 60%+")
                elif imp_change < -30:
                    result['action'] = 'Reduce upload density'
            
            # Log the check
            self.db.log_shadow_ban_check(
                result['impressions_trend'],
                result['ctr_trend'],
                result['suspicious'],
                result['action']
            )
            
            return result

        except Exception as e:
            logger.error(f"Error detecting shadow ban: {e}")
            return {'suspicious': False, 'action': 'Continue monitoring'}

    def apply_behavioral_drift(self) -> bool:
        """Apply behavioral drift every 7 days (modify patterns)"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Check last drift application
            cursor.execute('''SELECT MAX(applied_at) as last_drift 
                           FROM behavioral_drift''')
            result = cursor.fetchone()
            
            if result and result['last_drift']:
                last_drift = datetime.fromisoformat(result['last_drift'])
                days_since = (datetime.now() - last_drift).days
                
                if days_since < 7:
                    conn.close()
                    return False
            
            # Apply drifts
            drifts = [
                ('speech_speed', 1.0, random.uniform(-0.02, 0.02)),
                ('video_length', 10.0, random.uniform(-1.2, 1.2)),
                ('hook_aggressiveness', 0.5, random.uniform(-0.1, 0.1))
            ]
            
            for drift_type, old_val, delta in drifts:
                new_val = old_val + (old_val * delta)
                self.db.save_behavioral_drift(drift_type, old_val, new_val)
                logger.info(f"Behavioral drift applied: {drift_type} {old_val} → {new_val}")
            
            conn.close()
            return True

        except Exception as e:
            logger.error(f"Error applying behavioral drift: {e}")
            return False

    def optimize_strategy(self) -> Dict[str, Any]:
        """Automatically optimize content strategy"""
        try:
            analysis = self.analyze_recent_videos()
            strategy_updates = {
                'timestamp': datetime.now().isoformat(),
                'changes': []
            }
            
            # Analyze question type performance
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''SELECT question_type, AVG(ctr) as avg_ctr, COUNT(*) as count
                           FROM video_performance
                           WHERE upload_time > datetime('now', '-7 days')
                           GROUP BY question_type''')
            
            type_performance = cursor.fetchall()
            
            for row in type_performance:
                qt = row['question_type']
                ctr = row['avg_ctr']
                
                if ctr and ctr < 3:
                    strategy_updates['changes'].append(
                        f"Reduce {qt}: CTR {ctr:.1f}% < 3%"
                    )
                elif ctr and ctr > 8:
                    strategy_updates['changes'].append(
                        f"Increase {qt}: CTR {ctr:.1f}% > 8%"
                    )
            
            # Check retention
            cursor.execute('''SELECT AVG(completion_rate) as avg_completion
                           FROM video_performance
                           WHERE upload_time > datetime('now', '-7 days')''')
            
            retention_result = cursor.fetchone()
            avg_completion = retention_result['avg_completion'] if retention_result else 0
            
            if avg_completion and avg_completion < 50:
                strategy_updates['changes'].append(
                    f"Reduce video length: Completion {avg_completion:.1f}% < 50%"
                )
            
            conn.close()
            
            return strategy_updates

        except Exception as e:
            logger.error(f"Error optimizing strategy: {e}")
            return {'changes': []}
