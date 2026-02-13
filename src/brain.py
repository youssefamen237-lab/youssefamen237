#!/usr/bin/env python3

# First, verify critical dependencies before anything else
def _verify_dependencies():
    """Check critical packages are installed"""
    import sys
    critical = ['requests', 'schedule', 'database', 'youtube_api', 'content_generator']
    missing = []
    
    for module in critical:
        if module in ['database', 'youtube_api', 'content_generator', 'video_engine', 'upload_scheduler', 'content_safety', 'analytics', 'report_generator']:
            # Local modules
            continue
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    
    if missing:
        print(f"❌ Missing critical packages: {missing}")
        print("Run: pip install -r requirements.txt")
        sys.exit(1)

_verify_dependencies()

# Now do imports
import os
import sys
import logging
import random
import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, List, Tuple, Any
import schedule

# Add src to path
sys.path.insert(0, '/workspaces/youssefamen237/src')

from database import DatabaseManager
from youtube_api import YouTubeManager
from content_generator import ContentGenerator
from video_engine import VideoEngine
from upload_scheduler import UploadScheduler, PerformanceAnalyzer
from content_safety import ContentSafetyChecker, AudioValidator, ContentOptimizer, TrendInjector

# Setup logging
log_dir = '/workspaces/youssefamen237/logs'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, f'brain_{datetime.now().strftime("%Y%m%d")}.log')),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class SmartShortsEngine:
    """Main orchestration engine for YouTube Shorts production"""
    
    def __init__(self):
        logger.info("🚀 Initializing Smart Shorts Engine...")
        
        try:
            # Initialize managers
            self.db = DatabaseManager()
            self.youtube = YouTubeManager()
            self.content_gen = ContentGenerator(self.db)
            self.video_engine = VideoEngine()
            self.scheduler = UploadScheduler(self.db, self.youtube)
            self.analyzer = PerformanceAnalyzer(self.db, self.youtube)
            self.safety_checker = ContentSafetyChecker()
            self.audio_validator = AudioValidator(self.db)
            self.content_optimizer = ContentOptimizer(self.db)
            self.trend_injector = TrendInjector()
            
            # Configuration
            self.production_dir = '/tmp/shorts'
            os.makedirs(self.production_dir, exist_ok=True)
            
            logger.info("✅ Engine initialization complete!")
        except Exception as e:
            logger.error(f"❌ Fatal initialization error: {e}")
            logger.error("\n" + "="*60)
            logger.error("SETUP REQUIRED: Add GitHub Secrets")
            logger.error("="*60)
            logger.error("""
Missing API credentials. To fix this:

1. Go to GitHub Repository Settings
2. Click 'Secrets and variables' → 'Actions'
3. Add these secrets:
   - YT_CLIENT_ID_3
   - YT_CLIENT_SECRET_3
   - YT_REFRESH_TOKEN_3
   - YT_CHANNEL_ID
   - OPENAI_API_KEY (or GEMINI_API_KEY, GROQ_API_KEY)

For local testing:
   Create .env file with required keys
   Then run: source .env && python src/brain.py --single-cycle
""")
            raise

    def should_produce_content(self) -> bool:
        """Check if conditions are right for content production"""
        try:
            # Check if we should produce
            return self.content_gen.should_create_new_content() and self.scheduler.should_upload_now()
        except Exception as e:
            logger.error(f"Error checking production conditions: {e}")
            return False

    def generate_full_short(self) -> str:
        """Generate a complete YouTube Short from scratch"""
        try:
            logger.info("📝 Creating new short...")
            
            # Step 1: Generate question content
            logger.info("  → Generating question...")
            question_data = self.content_gen.generate_question()
            
            if not question_data:
                logger.warning("Failed to generate question")
                return None
            
            # Step 2: Safety check
            logger.info("  → Checking content safety...")
            title = self.content_gen.generate_title(question_data['type'])
            description = self.content_gen.generate_description(
                question_data['type'], question_data['cta']
            )
            
            is_safe, safety_reason = self.safety_checker.check_content_safety(
                question_data['question'],
                question_data['answer'],
                title,
                description
            )
            
            if not is_safe:
                logger.warning(f"Content rejected: {safety_reason}")
                # Retry with new content
                return self.generate_full_short()
            
            # Step 3: Get audio parameters
            logger.info("  → Generating audio parameters...")
            audio_params = self.content_gen.get_audio_parameters()
            
            # Step 4: Generate voiceover
            logger.info("  → Creating voiceover...")
            voiceover_path = self.audio_validator.generate_voiceover(
                question_data['question'],
                audio_params['voice_gender'],
                audio_params['speech_speed']
            )
            
            if not voiceover_path:
                logger.warning("Failed to generate voiceover")
                # Continue without audio
                voiceover_path = None
            
            # Step 5: Select background and music
            logger.info("  → Selecting assets...")
            bg_path = self.content_gen.select_background()
            music_path = self.content_gen.select_music()
            
            # Step 6: Get video structure
            logger.info("  → Determining video structure...")
            video_structure = self.content_gen.get_video_structure()
            
            # Step 7: Generate video
            logger.info("  → Creating video...")
            video_path = self.video_engine.create_short(
                question_data,
                audio_params,
                bg_path,
                music_path,
                video_structure
            )
            
            if not video_path:
                logger.warning("Failed to create video")
                return None
            
            # Step 8: Verify video quality
            logger.info("  → Verifying video quality...")
            quality = self.video_engine.verify_video_quality(video_path)
            
            if not quality.get('valid'):
                logger.warning(f"Video quality issue: {quality.get('error')}")
                return None
            
            # Step 9: Save content DNA
            logger.info("  → Saving content DNA...")
            metadata = self.content_gen.get_content_metadata(
                question_data, audio_params, bg_path, music_path
            )
            
            self.db.save_content_dna(
                question_data['question'],
                question_data['type'],
                metadata['hash_audio'],
                metadata['hash_background'],
                metadata['hash_music'],
                "",
                None
            )
            
            # Step 10: Optimize and prepare upload
            logger.info("  → Optimizing for upload...")
            
            optimized_title = self.content_optimizer.optimize_title(
                title, question_data['type']
            )
            optimized_description = self.content_optimizer.optimize_description(
                description, question_data['type'],
                self.content_gen.generate_hashtags(question_data['type'])
            )
            
            tags = self.content_gen.generate_hashtags(question_data['type'])
            
            logger.info(f"✅ Short created successfully: {video_path}")
            logger.info(f"   Title: {optimized_title}")
            logger.info(f"   Type: {question_data['type']}")
            logger.info(f"   Duration: {video_structure['total_length']:.1f}s")
            
            return {
                'video_path': video_path,
                'title': optimized_title,
                'description': optimized_description,
                'tags': tags,
                'question_data': question_data,
                'audio_params': audio_params,
                'video_structure': video_structure,
                'metadata': metadata
            }

        except Exception as e:
            logger.error(f"Error in generate_full_short: {e}", exc_info=True)
            return None

    async def upload_short_async(self, short_data: dict) -> bool:
        """Upload short to YouTube asynchronously"""
        try:
            logger.info("📤 Starting upload process...")
            
            # Add random delay to avoid detection (2-11 minutes)
            delay = self.scheduler.get_random_upload_delay()
            logger.info(f"   Waiting {delay}s before upload...")
            await asyncio.sleep(delay)
            
            video_id = await self.scheduler.execute_upload(
                short_data['video_path'],
                short_data['title'],
                short_data['description'],
                short_data['tags'],
                short_data['question_data']
            )
            
            if video_id:
                logger.info(f"✅ Upload successful! Video ID: {video_id}")
                
                # Update database with video info
                self.db.save_video_performance({
                    'video_id': video_id,
                    'question_type': short_data['question_data']['type'],
                    'video_length': short_data['video_structure']['total_length'],
                    'voice_gender': short_data['audio_params']['voice_gender'],
                    'background_type': 'gradient' if 'gradient' in short_data['metadata']['hash_background'] else 'custom',
                    'upload_time': datetime.now().isoformat(),
                    'title_format': 'Optimized',
                    'cta_used': short_data['question_data']['cta'],
                    'timer_duration': short_data['video_structure']['timer_duration'],
                    'speech_speed': short_data['audio_params']['speech_speed'],
                    'watch_time': 0,
                    'completion_rate': 0,
                    'ctr': 0,
                    'comments_count': 0,
                    'rewatch_rate': 0,
                    'impressions': 0
                })
                
                return True
            else:
                logger.error("Upload failed")
                return False

        except Exception as e:
            logger.error(f"Error uploading short: {e}", exc_info=True)
            return False

    def analyze_performance(self) -> Dict[str, any]:
        """Analyze recent performance"""
        try:
            logger.info("📊 Analyzing performance...")
            
            analysis = self.analyzer.analyze_recent_videos()
            
            logger.info(f"   Videos analyzed: {analysis.get('videos_analyzed', 0)}")
            logger.info(f"   Average performance: {analysis.get('average_performance', 0):.2f}")
            
            if analysis.get('insights'):
                for insight in analysis['insights']:
                    logger.info(f"   → {insight}")
            
            return analysis

        except Exception as e:
            logger.error(f"Error analyzing performance: {e}")
            return {}

    def optimize_strategy(self) -> Dict[str, any]:
        """Automatically optimize strategy"""
        try:
            logger.info("🧠 Optimizing strategy...")
            
            updates = self.analyzer.optimize_strategy()
            
            if updates.get('changes'):
                for change in updates['changes']:
                    logger.info(f"   → {change}")
            else:
                logger.info("   No adjustments needed")
            
            return updates

        except Exception as e:
            logger.error(f"Error optimizing strategy: {e}")
            return {}

    def check_shadow_ban(self) -> Dict[str, any]:
        """Check for shadow ban"""
        try:
            logger.info("🔍 Checking shadow ban status...")
            
            result = self.analyzer.detect_shadow_ban()
            
            if result['suspicious']:
                logger.warning(f"   ⚠️ ALERT: {result['action']}")
            else:
                logger.info(f"   ✅ Status: Normal - {result['action']}")
            
            return result

        except Exception as e:
            logger.error(f"Error checking shadow ban: {e}")
            return {}

    def apply_behavioral_drift(self) -> bool:
        """Apply behavioral drift every 7 days"""
        try:
            logger.info("🔄 Checking behavioral drift...")
            
            if self.analyzer.apply_behavioral_drift():
                logger.info("   ✅ Behavioral drift applied")
                return True
            else:
                logger.info("   → Next drift in 7 days")
                return False

        except Exception as e:
            logger.error(f"Error applying behavioral drift: {e}")
            return False

    def inject_trends(self) -> Optional[Dict]:
        """Inject trending topics into content"""
        try:
            logger.info("🔥 Checking for trends...")
            
            trends = self.trend_injector.get_trending_topics()
            
            if trends:
                selected_trend = random.choice(trends[:5])
                logger.info(f"   Selected trend: {selected_trend}")
                
                content = self.trend_injector.create_trend_based_content(selected_trend)
                
                if content:
                    logger.info("   ✅ Trend content created")
                    return content
            
            logger.info("   → No trends available")
            return None

        except Exception as e:
            logger.error(f"Error injecting trends: {e}")
            return None

    def get_analytics_summary(self) -> Dict[str, any]:
        """Get analytics summary"""
        try:
            logger.info("📈 Generating analytics summary...")
            
            summary = self.db.get_analytics_summary()
            
            logger.info(f"   Total videos: {summary.get('total_videos', 0)}")
            logger.info(f"   Average score: {summary.get('average_score', 0):.2f}")
            logger.info(f"   Latest 7 days: {summary.get('recent_7_days', 0)} videos")
            
            return summary

        except Exception as e:
            logger.error(f"Error getting analytics: {e}")
            return {}

    def cleanup_and_maintain(self) -> bool:
        """Cleanup and maintenance tasks"""
        try:
            logger.info("🧹 Running maintenance...")
            
            # Clean temp files
            self.video_engine.cleanup_temp_files()
            
            # Clear old API failures
            self.db.clear_old_api_failures(days=7)
            
            logger.info("   ✅ Maintenance complete")
            return True

        except Exception as e:
            logger.error(f"Error during maintenance: {e}")
            return False

    def run_daily_cycle(self):
        """Run a daily production cycle with robust error handling"""
        cycle_start = time.time()
        max_cycle_time = 350 * 60  # 350 minutes (leave 50 min buffer for GitHub Actions 400 min limit)
        
        try:
            logger.info("=" * 60)
            logger.info("🎬 STARTING DAILY CYCLE")
            logger.info("=" * 60)
            
            # Check time before analytics
            if time.time() - cycle_start > max_cycle_time:
                logger.warning("⏰ Time limit approaching, skipping analytics...")
            else:
                try:
                    # Analysis and optimization (with timeout)
                    self.get_analytics_summary()
                except Exception as e:
                    logger.warning(f"Analytics failed (non-fatal): {e}")
                
                if datetime.now().weekday() % 2 == 0:
                    try:
                        self.analyze_performance()
                        self.optimize_strategy()
                    except Exception as e:
                        logger.warning(f"Strategy optimization failed (non-fatal): {e}")
                
                try:
                    self.check_shadow_ban()
                except Exception as e:
                    logger.warning(f"Shadow ban check failed (non-fatal): {e}")
                
                if datetime.now().weekday() == 0:
                    try:
                        self.apply_behavioral_drift()
                    except Exception as e:
                        logger.warning(f"Behavioral drift failed (non-fatal): {e}")
            
            # Content production (4-8 times per day)
            try:
                daily_target = self.scheduler.calculate_optimal_upload_density()
            except Exception as e:
                logger.warning(f"Could not calculate optimal density, using default: {e}")
                daily_target = 4
            
            produced_count = 0
            logger.info(f"📊 Daily target: {daily_target} videos")
            
            for i in range(daily_target):
                # Check time remaining
                elapsed = time.time() - cycle_start
                if elapsed > max_cycle_time:
                    logger.warning(f"⏰ Time limit reached! Stopping production. (Elapsed: {elapsed/60:.1f}m)")
                    break
                
                try:
                    if not self.should_produce_content():
                        logger.info("⏸️ Upload conditions not met")
                        break
                    
                    # Generate short
                    short_data = self.generate_full_short()
                    
                    if not short_data:
                        logger.warning(f"Failed to generate short #{i+1}")
                        continue
                    
                    # Check time before upload
                    if time.time() - cycle_start > max_cycle_time - (10 * 60):
                        logger.warning("⏰ Approaching time limit, aborting remaining uploads")
                        break
                    
                    # Upload asynchronously
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    
                    success = loop.run_until_complete(
                        self.upload_short_async(short_data)
                    )
                    
                    if success:
                        produced_count += 1
                        
                        # Random delay between uploads (5-15 minutes)
                        if i < daily_target - 1:
                            delay = random.randint(5 * 60, 15 * 60)
                            remaining = max_cycle_time - (time.time() - cycle_start)
                            if remaining > delay:
                                logger.info(f"⏳ Waiting {delay}s before next production...")
                                time.sleep(delay)
                            else:
                                logger.warning("Not enough time for next upload")
                                break
                    else:
                        logger.warning(f"Upload failed for short #{i+1}")
                
                except Exception as e:
                    logger.error(f"Error producing short #{i+1}: {e}", exc_info=True)
                    continue
            
            logger.info(f"✅ Daily cycle complete! Produced: {produced_count} video(s)")
            
            # Cleanup
            try:
                self.cleanup_and_maintain()
            except Exception as e:
                logger.warning(f"Cleanup failed (non-fatal): {e}")
            
            logger.info("=" * 60)
            logger.info(f"Total time: {(time.time() - cycle_start)/60:.1f}m")

        except KeyboardInterrupt:
            logger.info("Cycle interrupted by user")
        except Exception as e:
            logger.error(f"Fatal error in daily cycle: {e}", exc_info=True)
            logger.error("Attempting graceful shutdown...")
            try:
                self.cleanup_and_maintain()
            except:
                pass

    def schedule_jobs(self):
        """Schedule recurring jobs"""
        try:
            logger.info("⏰ Scheduling jobs...")
            
            # Get optimal upload time
            upload_time = self.scheduler.get_optimal_upload_time()
            
            if upload_time:
                time_str = upload_time.strftime("%H:%M")
                logger.info(f"   → Daily cycle at {time_str}")
                schedule.every().day.at(time_str).do(self.run_daily_cycle)
            else:
                # Fallback to fixed time
                schedule.every().day.at("17:00").do(self.run_daily_cycle)
            
            # Analytics (daily)
            schedule.every().day.at("08:00").do(self.get_analytics_summary)
            
            # Performance analysis (every 2 days)
            schedule.every(2).days.do(self.analyze_performance)
            
            # Shadow ban check (daily)
            schedule.every().day.at("12:00").do(self.check_shadow_ban)
            
            logger.info("✅ Jobs scheduled!")
            
            # Run the first cycle immediately
            logger.info("🚀 Running initial production cycle...")
            self.run_daily_cycle()
            
            # Keep scheduler running
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute

        except Exception as e:
            logger.error(f"Error in scheduling: {e}", exc_info=True)
            # Retry after 1 hour
            logger.info("Retrying in 1 hour...")
            time.sleep(3600)
            self.schedule_jobs()


def main():
    """Main entry point with robust error handling"""
    try:
        import argparse
        
        parser = argparse.ArgumentParser(description='Smart Shorts YouTube Automation Engine')
        parser.add_argument('--single-cycle', action='store_true', 
                          help='Run a single production cycle and exit')
        parser.add_argument('--analyse-only', action='store_true',
                          help='Only run analysis, don\'t produce content')
        parser.add_argument('--schedule', action='store_true', default=True,
                          help='Run scheduler (default)')
        
        args = parser.parse_args()
        
        logger.info("🎯 YouTube Shorts Smart Engine Starting...")
        logger.info(f"⏰ Timestamp: {datetime.now().isoformat()}")
        
        try:
            engine = SmartShortsEngine()
        except Exception as e:
            logger.error(f"Failed to initialize engine: {e}")
            logger.error("\n⚠️  SETUP REQUIRED")
            logger.error("Please make sure:")
            logger.error("  1. All API keys are added to GitHub Secrets")
            logger.error("  2. YouTube credentials are valid")
            logger.error("  3. Database is initialized")
            sys.exit(1)
        
        if args.single_cycle:
            logger.info("Running single production cycle...")
            try:
                engine.run_daily_cycle()
                logger.info("✅ Single cycle complete!")
                sys.exit(0)
            except Exception as e:
                logger.error(f"Single cycle failed: {e}", exc_info=True)
                sys.exit(1)
        
        elif args.analyse_only:
            logger.info("Running analysis only...")
            try:
                engine.analyze_performance()
                engine.optimize_strategy()
                engine.check_shadow_ban()
                logger.info("✅ Analysis complete!")
                sys.exit(0)
            except Exception as e:
                logger.error(f"Analysis failed: {e}", exc_info=True)
                sys.exit(1)
        
        else:
            # Full scheduler mode
            logger.info("Starting scheduler (continuous mode)...")
            try:
                engine.schedule_jobs()
            except KeyboardInterrupt:
                logger.info("Scheduler interrupted by user")
                sys.exit(0)
            except Exception as e:
                logger.error(f"Scheduler error: {e}", exc_info=True)
                sys.exit(1)

    except KeyboardInterrupt:
        logger.info("🛑 Shutting down gracefully...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
