import os
import time
import logging
from datetime import datetime, timedelta

from engines.shorts_engine import ShortsEngine
from engines.long_video_engine import LongVideoEngine
from engines.risk_management import RiskManagement
from core.project_manager import ProjectManager
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def setup_logging():
    """Setup main application logging"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        filename='logs/system.log'
    )
    
    # Also log to console for critical errors
    console = logging.StreamHandler()
    console.setLevel(logging.ERROR)
    formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)

def main():
    """Main application loop"""
    setup_logging()
    logger = logging.getLogger('Main')
    logger.info("Starting Self-Governing AI YouTube Channel System")
    
    # Initialize core components
    shorts_engine = ShortsEngine()
    long_video_engine = LongVideoEngine()
    risk_manager = RiskManagement()
    project_manager = ProjectManager()
    
    # First run: publish immediate content as required
    logger.info("Executing first run - publishing immediate content")
    
    # Publish initial Shorts
    for _ in range(4):
        short_path = shorts_engine.generate_short()
        if short_path and shorts_engine.publish_short(short_path):
            risk_manager.record_action("publish")
            logger.info("Published initial Short")
        time.sleep(2)  # Small delay between publishes
    
    # Publish initial Long video
    long_video_path = long_video_engine.generate_long_video()
    if long_video_path and long_video_engine.publish_video(long_video_path):
        risk_manager.record_action("publish")
        logger.info("Published initial Long video")
    
    logger.info("Initial content published. Entering continuous operation mode.")
    
    # Main operation loop
    while True:
        try:
            current_time = datetime.now()
            
            # Run project manager analysis periodically
            if project_manager.should_analyze():
                project_manager.analyze_performance()
            
            # Check if we should publish Shorts
            shorts_needed = 4 - shorts_engine.today_published_count()
            for _ in range(shorts_needed):
                if shorts_engine.should_publish_now():
                    short_path = shorts_engine.generate_short()
                    if short_path and shorts_engine.publish_short(short_path):
                        risk_manager.record_action("publish")
                        shorts_engine.increment_published_count()
            
            # Check if we should publish Long videos
            if long_video_engine.should_publish_now():
                long_video_path = long_video_engine.generate_long_video()
                if long_video_path and long_video_engine.publish_video(long_video_path):
                    risk_manager.record_action("publish")
            
            # Check risk conditions and adjust behavior if needed
            if risk_manager.should_modify_behavior():
                logger.warning("Risk conditions detected. Adjusting content strategy.")
                # Would implement behavior modification here
            
            # Sleep for a reasonable interval before next check
            time.sleep(300)  # 5 minutes
            
        except Exception as e:
            logger.error(f"Main loop error: {str(e)}")
            # Continue running despite errors per requirements

if __name__ == "__main__":
    main()
