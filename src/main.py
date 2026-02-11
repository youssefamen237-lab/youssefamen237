import argparse
import os
import sys
from datetime import datetime

from content_generator import ContentGenerator
from video_assembler import VideoAssembler
from uploader import YouTubeUploader
from analytics_engine import AnalyticsEngine
from strategy_engine import StrategyEngine
from dna_tracker import DnaTracker
from safety_checker import SafetyChecker
from human_simulator import HumanSimulator
from utils import logger, load_json, save_json

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['generate', 'analytics', 'evolve', 'recovery'], required=True)
    args = parser.parse_args()
    
    config = load_json('config.json')
    
    if args.mode == 'generate':
        run_production_pipeline(config)
    elif args.mode == 'analytics':
        run_analytics_update(config)
    elif args.mode == 'evolve':
        run_strategy_evolution(config)
    elif args.mode == 'recovery':
        run_recovery_mode(config)

def run_production_pipeline(config):
    """Main content generation and upload workflow"""
    logger.info("🚀 Starting Self-Governing Production Pipeline")
    
    # Initialize components
    dna = DnaTracker()
    safety = SafetyChecker()
    human = HumanSimulator(config)
    content_gen = ContentGenerator(config)
    video_asm = VideoAssembler(config)
    uploader = YouTubeUploader()
    
    # Check upload density limits
    state = load_json('data/strategy_state.json') or {}
    today_uploads = state.get('today_uploads', 0)
    if today_uploads >= config['production']['daily_uploads']['max']:
        logger.info("📊 Daily upload limit reached. Pausing.")
        return
    
    # Shadow ban detection
    analytics = AnalyticsEngine(config)
    if analytics.detect_shadow_ban():
        logger.warning("🚫 Shadow ban detected. Initiating 48h pause protocol.")
        state['pause_until'] = (datetime.now().timestamp() + 48*3600)
        save_json('data/strategy_state.json', state)
        return
    
    # Generate content with retries
    max_attempts = 5
    for attempt in range(max_attempts):
        logger.info(f"🎲 Content generation attempt {attempt + 1}")
        
        # Get trending context every 3 days
        if attempt == 0 and state.get('last_trend_inject', 0) < (datetime.now().timestamp() - 3*86400):
            trend_data = content_gen.inject_trend()
        else:
            trend_data = None
            
        content = content_gen.generate(trend_context=trend_data)
        
        # DNA Check
        if dna.is_duplicate(content):
            logger.warning("🧬 Duplicate detected. Regenerating...")
            continue
            
        # Safety Check
        if not safety.validate(content):
            logger.warning("🛡️ Content failed safety check. Regenerating...")
            continue
            
        # Assemble video with human variance
        video_params = human.generate_video_params()
        video_path = video_asm.create(content, video_params)
        
        if not video_path:
            continue
            
        # Update DNA
        dna.register_content(content, video_params)
        
        # Upload with human delay already handled by workflow
        try:
            video_id = uploader.upload(video_path, content, human.generate_upload_metadata())
            if video_id:
                # Record analytics entry
                analytics.record_upload(video_id, content, video_params)
                # Update state
                state['today_uploads'] = today_uploads + 1
                state['last_upload'] = datetime.now().isoformat()
                save_json('data/strategy_state.json', state)
                logger.info(f"✅ Success: https://youtube.com/shorts/{video_id}")
                break
        except Exception as e:
            logger.error(f"❌ Upload failed: {e}")
            handle_upload_failure(video_path, content)

def run_analytics_update(config):
    """Update performance metrics and trigger adaptations"""
    logger.info("📈 Collecting Analytics...")
    analytics = AnalyticsEngine(config)
    analytics.collect_latest_metrics()
    
    # Check for performance drops
    state = load_json('data/strategy_state.json') or {}
    recent = analytics.get_recent_performance(72)  # Last 72 hours
    
    if recent['avg_ctr'] < config['thresholds']['low_ctr_threshold']:
        logger.warning("📉 Low CTR detected. Reducing upload density by 30%.")
        state['density_modifier'] = 0.7
    elif recent['avg_ctr'] > config['thresholds']['high_ctr_threshold']:
        logger.info("📈 High performance. Increasing density by 20%.")
        state['density_modifier'] = 1.2
    else:
        state['density_modifier'] = 1.0
        
    save_json('data/strategy_state.json', state)

def run_strategy_evolution(config):
    """Weekly strategy adjustment"""
    logger.info("🧬 Running Weekly Evolution...")
    strategy = StrategyEngine(config)
    strategy.evolve()
    strategy.apply_behavioral_drift()

def run_recovery_mode(config):
    """Handle failed uploads from queue"""
    logger.info("🔄 Recovery Mode...")
    queue = load_json('data/upload_queue.json') or []
    uploader = YouTubeUploader()
    
    for item in queue[:3]:  # Process max 3
        try:
            video_id = uploader.upload(item['path'], item['content'], item['metadata'])
            if video_id:
                queue.remove(item)
        except Exception as e:
            logger.error(f"Recovery failed for {item['path']}: {e}")
            
    save_json('data/upload_queue.json', queue)

def handle_upload_failure(video_path, content):
    """Queue for retry"""
    queue = load_json('data/upload_queue.json') or []
    queue.append({
        'path': video_path,
        'content': content,
        'timestamp': datetime.now().isoformat(),
        'retry_count': 0
    })
    save_json('data/upload_queue.json', queue)
    logger.info("⏳ Added to retry queue")

if __name__ == "__main__":
    main()
