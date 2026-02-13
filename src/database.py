import sqlite3
import json
import hashlib
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path: str = "/workspaces/youssefamen237/db/system.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.init_database()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_database(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        # Content DNA Tracking
        cursor.execute('''CREATE TABLE IF NOT EXISTS content_dna (
            id INTEGER PRIMARY KEY,
            hash_question TEXT UNIQUE,
            hash_audio TEXT,
            hash_background TEXT,
            hash_music TEXT,
            hash_order TEXT,
            question_text TEXT,
            created_at TIMESTAMP,
            embedding_vector BLOB,
            content_type TEXT
        )''')

        # Video Performance Tracking
        cursor.execute('''CREATE TABLE IF NOT EXISTS video_performance (
            id INTEGER PRIMARY KEY,
            video_id TEXT UNIQUE,
            question_type TEXT,
            video_length REAL,
            voice_gender TEXT,
            background_type TEXT,
            upload_time TIMESTAMP,
            title_format TEXT,
            cta_used TEXT,
            timer_duration REAL,
            speech_speed REAL,
            watch_time REAL,
            completion_rate REAL,
            ctr REAL,
            comments_count INTEGER,
            rewatch_rate REAL,
            impressions INTEGER,
            performance_score REAL,
            best_watch_point_3s REAL,
            best_watch_point_7s REAL,
            drop_points TEXT,
            analyzed_at TIMESTAMP
        )''')

        # Upload History & Scheduling
        cursor.execute('''CREATE TABLE IF NOT EXISTS upload_history (
            id INTEGER PRIMARY KEY,
            video_id TEXT UNIQUE,
            title TEXT,
            description TEXT,
            content_type TEXT,
            upload_timestamp TIMESTAMP,
            next_optimal_time TIMESTAMP,
            upload_succeeded BOOLEAN,
            failure_reason TEXT,
            retry_count INTEGER,
            created_at TIMESTAMP
        )''')

        # Strategy Evolution
        cursor.execute('''CREATE TABLE IF NOT EXISTS strategy_evolution (
            id INTEGER PRIMARY KEY,
            date TIMESTAMP,
            question_type_weights TEXT,
            voice_gender_preference TEXT,
            average_video_length REAL,
            average_speech_speed REAL,
            cta_variations TEXT,
            upload_density INTEGER,
            active_status BOOLEAN,
            shadow_ban_suspected BOOLEAN
        )''')

        # Music Metadata
        cursor.execute('''CREATE TABLE IF NOT EXISTS music_metadata (
            id INTEGER PRIMARY KEY,
            filename TEXT UNIQUE,
            bpm INTEGER,
            mood TEXT,
            usage_count INTEGER,
            last_used TIMESTAMP,
            duration REAL,
            energy_level TEXT
        )''')

        # Background Tracking
        cursor.execute('''CREATE TABLE IF NOT EXISTS background_tracking (
            id INTEGER PRIMARY KEY,
            filename TEXT UNIQUE,
            type TEXT,
            last_used TIMESTAMP,
            usage_count INTEGER,
            aesthetic_quality REAL
        )''')

        # A/B Testing Framework
        cursor.execute('''CREATE TABLE IF NOT EXISTS ab_tests (
            id INTEGER PRIMARY KEY,
            test_name TEXT,
            variant_a TEXT,
            variant_b TEXT,
            test_duration INTEGER,
            videos_variant_a INTEGER,
            videos_variant_b INTEGER,
            avg_score_a REAL,
            avg_score_b REAL,
            winner TEXT,
            started_at TIMESTAMP,
            ended_at TIMESTAMP
        )''')

        # Comment Automation Log
        cursor.execute('''CREATE TABLE IF NOT EXISTS comment_automation (
            id INTEGER PRIMARY KEY,
            video_id TEXT,
            comment_id TEXT,
            reply_text TEXT,
            replied_at TIMESTAMP,
            engagement_type TEXT
        )''')

        # Playlist Management
        cursor.execute('''CREATE TABLE IF NOT EXISTS playlist_management (
            id INTEGER PRIMARY KEY,
            playlist_id TEXT,
            question_type TEXT,
            video_id TEXT,
            position INTEGER,
            avg_playlist_score REAL,
            updated_at TIMESTAMP
        )''')

        # API Failure Log
        cursor.execute('''CREATE TABLE IF NOT EXISTS api_failures (
            id INTEGER PRIMARY KEY,
            api_name TEXT,
            error_message TEXT,
            timestamp TIMESTAMP,
            retry_scheduled BOOLEAN
        )''')

        # Behavioral Drift Log
        cursor.execute('''CREATE TABLE IF NOT EXISTS behavioral_drift (
            id INTEGER PRIMARY KEY,
            drift_type TEXT,
            old_value REAL,
            new_value REAL,
            applied_at TIMESTAMP
        )''')

        # Shadow Ban Detection
        cursor.execute('''CREATE TABLE IF NOT EXISTS shadow_ban_detection (
            id INTEGER PRIMARY KEY,
            check_date TIMESTAMP,
            impressions_trend REAL,
            ctr_trend REAL,
            is_suspicious BOOLEAN,
            action_taken TEXT
        )''')

        # Content Statistics
        cursor.execute('''CREATE TABLE IF NOT EXISTS content_stats (
            id INTEGER PRIMARY KEY,
            content_type TEXT,
            avg_performance REAL,
            video_count INTEGER,
            retention_trend REAL,
            ctr_trend REAL,
            updated_at TIMESTAMP
        )''')

        conn.commit()
        conn.close()

    def save_content_dna(self, question_text: str, content_type: str, 
                        hash_audio: str, hash_background: str, 
                        hash_music: str, hash_order: str, 
                        embedding_vector: Optional[bytes] = None) -> str:
        try:
            hash_question = hashlib.sha256(question_text.encode()).hexdigest()
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''INSERT OR REPLACE INTO content_dna 
                (hash_question, question_text, hash_audio, hash_background, 
                 hash_music, hash_order, created_at, embedding_vector, content_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (hash_question, question_text, hash_audio, hash_background,
                 hash_music, hash_order, datetime.now().isoformat(), embedding_vector, content_type))
            conn.commit()
            conn.close()
            return hash_question
        except Exception as e:
            logger.error(f"Error saving content DNA: {e}")
            return None

    def check_content_similarity(self, question_text: str, threshold: float = 0.7) -> bool:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM content_dna ORDER BY created_at DESC LIMIT 100")
            recent_contents = cursor.fetchall()
            conn.close()

            for content in recent_contents:
                similarity = self._calculate_edit_distance(
                    question_text.lower(), 
                    content['question_text'].lower()
                )
                if similarity >= threshold:
                    return True
            return False
        except Exception as e:
            logger.error(f"Error checking content similarity: {e}")
            return False

    def _calculate_edit_distance(self, s1: str, s2: str) -> float:
        if len(s1) < len(s2):
            return self._calculate_edit_distance(s2, s1)
        if len(s2) == 0:
            return 0.0
        
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        distance = previous_row[-1]
        max_length = max(len(s1), len(s2))
        return 1 - (distance / max_length) if max_length > 0 else 1.0

    def save_video_performance(self, video_data: Dict[str, Any]) -> bool:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            performance_score = self._calculate_performance_score(video_data)
            
            cursor.execute('''INSERT OR REPLACE INTO video_performance 
                (video_id, question_type, video_length, voice_gender, 
                 background_type, upload_time, title_format, cta_used, 
                 timer_duration, speech_speed, watch_time, completion_rate, 
                 ctr, comments_count, rewatch_rate, impressions, 
                 performance_score, best_watch_point_3s, best_watch_point_7s, 
                 drop_points, analyzed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (video_data.get('video_id'),
                 video_data.get('question_type'),
                 video_data.get('video_length'),
                 video_data.get('voice_gender'),
                 video_data.get('background_type'),
                 video_data.get('upload_time'),
                 video_data.get('title_format'),
                 video_data.get('cta_used'),
                 video_data.get('timer_duration', 5.0),
                 video_data.get('speech_speed', 1.0),
                 video_data.get('watch_time', 0),
                 video_data.get('completion_rate', 0),
                 video_data.get('ctr', 0),
                 video_data.get('comments_count', 0),
                 video_data.get('rewatch_rate', 0),
                 video_data.get('impressions', 0),
                 performance_score,
                 video_data.get('best_watch_point_3s', 0),
                 video_data.get('best_watch_point_7s', 0),
                 json.dumps(video_data.get('drop_points', [])),
                 datetime.now().isoformat()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error saving video performance: {e}")
            return False

    def _calculate_performance_score(self, video_data: Dict[str, Any]) -> float:
        watch_time_weight = 0.35
        completion_weight = 0.25
        ctr_weight = 0.15
        comments_weight = 0.1
        rewatch_weight = 0.15
        
        watch_time = min(video_data.get('watch_time', 0) / 10, 1.0)
        completion = video_data.get('completion_rate', 0) / 100
        ctr = min(video_data.get('ctr', 0) / 20, 1.0)
        comments = min(video_data.get('comments_count', 0) / 100, 1.0)
        rewatch = video_data.get('rewatch_rate', 0) / 100
        
        score = (watch_time * watch_time_weight +
                completion * completion_weight +
                ctr * ctr_weight +
                comments * comments_weight +
                rewatch * rewatch_weight)
        
        return round(score, 3)

    def get_strategy_analysis(self) -> Dict[str, Any]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Get recent video performance
            cursor.execute('''SELECT question_type, ctr, completion_rate, 
                            voice_gender, AVG(performance_score) as avg_score,
                            COUNT(*) as count
                         FROM video_performance 
                         WHERE analyzed_at > datetime('now', '-7 days')
                         GROUP BY question_type, voice_gender''')
            
            performance_data = cursor.fetchall()
            
            strategy = {
                'question_type_performance': {},
                'voice_gender_performance': {},
                'next_adjustments': [],
                'last_updated': datetime.now().isoformat()
            }
            
            for row in performance_data:
                qt = row['question_type']
                if qt not in strategy['question_type_performance']:
                    strategy['question_type_performance'][qt] = {
                        'avg_score': row['avg_score'],
                        'count': row['count'],
                        'ctr': row['ctr'],
                        'completion': row['completion_rate']
                    }
                
                vg = row['voice_gender']
                if vg not in strategy['voice_gender_performance']:
                    strategy['voice_gender_performance'][vg] = {
                        'avg_score': row['avg_score'],
                        'count': row['count']
                    }
            
            # Generate adjustments
            for qt, data in strategy['question_type_performance'].items():
                if data.get('ctr', 0) < 3:
                    strategy['next_adjustments'].append(
                        f"Consider reducing {qt} (CTR: {data['ctr']:.1f}%)"
                    )
                elif data.get('ctr', 0) > 8:
                    strategy['next_adjustments'].append(
                        f"Increase {qt} (CTR: {data['ctr']:.1f}%)"
                    )
            
            conn.close()
            return strategy
        except Exception as e:
            logger.error(f"Error getting strategy analysis: {e}")
            return {}

    def record_upload(self, video_id: str, title: str, description: str,
                     content_type: str, success: bool, failure_reason: str = None) -> bool:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''INSERT INTO upload_history 
                (video_id, title, description, content_type, 
                 upload_timestamp, upload_succeeded, failure_reason, 
                 retry_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (video_id, title, description, content_type,
                 datetime.now().isoformat(), success, failure_reason,
                 0, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error recording upload: {e}")
            return False

    def get_music_metadata(self, filename: str) -> Optional[Dict]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM music_metadata WHERE filename = ?", (filename,))
            result = cursor.fetchone()
            conn.close()
            return dict(result) if result else None
        except Exception as e:
            logger.error(f"Error getting music metadata: {e}")
            return None

    def update_music_metadata(self, filename: str, bpm: int, mood: str, 
                             duration: float, energy_level: str) -> bool:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''INSERT OR REPLACE INTO music_metadata 
                (filename, bpm, mood, usage_count, last_used, duration, energy_level)
                VALUES (?, ?, ?, COALESCE((SELECT usage_count FROM music_metadata 
                        WHERE filename = ?), 0) + 1, ?, ?, ?)''',
                (filename, bpm, mood, filename, datetime.now().isoformat(), duration, energy_level))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error updating music metadata: {e}")
            return False

    def get_least_used_music(self, limit: int = 5) -> List[str]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''SELECT filename FROM music_metadata 
                           ORDER BY usage_count ASC, last_used ASC 
                           LIMIT ?''', (limit,))
            results = cursor.fetchall()
            conn.close()
            return [r[0] for r in results]
        except Exception as e:
            logger.error(f"Error getting least used music: {e}")
            return []

    def get_least_used_backgrounds(self, limit: int = 5) -> List[str]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''SELECT filename FROM background_tracking 
                           WHERE last_used < datetime('now', '-7 days')
                           ORDER BY usage_count ASC
                           LIMIT ?''', (limit,))
            results = cursor.fetchall()
            conn.close()
            return [r[0] for r in results]
        except Exception as e:
            logger.error(f"Error getting least used backgrounds: {e}")
            return []

    def save_behavioral_drift(self, drift_type: str, old_value: float, new_value: float) -> bool:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''INSERT INTO behavioral_drift 
                (drift_type, old_value, new_value, applied_at)
                VALUES (?, ?, ?, ?)''',
                (drift_type, old_value, new_value, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error saving behavioral drift: {e}")
            return False

    def log_shadow_ban_check(self, impressions_trend: float, ctr_trend: float, 
                            is_suspicious: bool, action_taken: str) -> bool:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''INSERT INTO shadow_ban_detection 
                (check_date, impressions_trend, ctr_trend, is_suspicious, action_taken)
                VALUES (?, ?, ?, ?, ?)''',
                (datetime.now().isoformat(), impressions_trend, ctr_trend, is_suspicious, action_taken))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error logging shadow ban check: {e}")
            return False

    def get_performance_trends(self, days: int = 30) -> Dict[str, Any]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''SELECT 
                            DATE(upload_time) as date,
                            AVG(performance_score) as avg_score,
                            AVG(ctr) as avg_ctr,
                            AVG(completion_rate) as avg_completion,
                            COUNT(*) as videos_count
                         FROM video_performance 
                         WHERE upload_time > datetime('now', '-' || ? || ' days')
                         GROUP BY DATE(upload_time)
                         ORDER BY date DESC''', (days,))
            
            results = cursor.fetchall()
            conn.close()
            
            trends = {
                'dates': [],
                'scores': [],
                'ctr': [],
                'completion': [],
                'video_counts': []
            }
            
            for row in results:
                trends['dates'].append(row['date'])
                trends['scores'].append(row['avg_score'] or 0)
                trends['ctr'].append(row['avg_ctr'] or 0)
                trends['completion'].append(row['avg_completion'] or 0)
                trends['video_counts'].append(row['videos_count'])
            
            return trends
        except Exception as e:
            logger.error(f"Error getting performance trends: {e}")
            return {}

    def clear_old_api_failures(self, days: int = 7) -> bool:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''DELETE FROM api_failures 
                           WHERE timestamp < datetime('now', '-' || ? || ' days')''', (days,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error clearing old API failures: {e}")
            return False

    def get_analytics_summary(self) -> Dict[str, Any]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Total videos
            cursor.execute("SELECT COUNT(*) as count FROM video_performance")
            total_videos = cursor.fetchone()['count']
            
            # Average performance
            cursor.execute("SELECT AVG(performance_score) as avg_score FROM video_performance")
            avg_score = cursor.fetchone()['avg_score'] or 0
            
            # Top performing question type
            cursor.execute('''SELECT question_type, AVG(performance_score) as avg_score 
                           FROM video_performance 
                           GROUP BY question_type 
                           ORDER BY avg_score DESC LIMIT 1''')
            top_type = cursor.fetchone()
            
            # Recent videos (last 7 days)
            cursor.execute('''SELECT COUNT(*) as count FROM video_performance 
                           WHERE upload_time > datetime('now', '-7 days')''')
            recent_count = cursor.fetchone()['count']
            
            conn.close()
            
            return {
                'total_videos': total_videos,
                'average_score': round(avg_score, 3),
                'top_question_type': top_type['question_type'] if top_type else 'N/A',
                'recent_7_days': recent_count,
                'last_updated': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting analytics summary: {e}")
            return {}
