import argparse
import sys
import random
import logging
from core.ai_engine import GenerativeAI
from core.video_processor import VideoDirector
from core.youtube_client import YouTubeClient
from core.local_db import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")

def build_short_video(db, ai, video_sys, yt_client):
    logging.info("--- [ENGINE] Generating New Viral Short ---")
    data = ai.generate_quiz_script(db)
    if not data:
        logging.error("Failed to generate concept. Falling back to simple default...")
        # Fallback script included for total failover
        data = {
            "template": "Multiple Choice", "question": "What is the largest planet in our solar system?",
            "options":["Mars", "Jupiter", "Earth", "Saturn"], "answer": "Jupiter", 
            "cta": "Like & comment if you knew!", "topic": "science"
        }
    
    # 2. Build Audio Assets (SFX + AI Speech adjusted)
    final_video_path, metadata = video_sys.create_masterpiece(data, type="short")
    
    if final_video_path:
        # 3. Optimize Meta with AI
        seo_meta = ai.generate_seo_metadata(data)
        
        # 4. Upload System
        success = yt_client.upload_video(final_video_path, seo_meta, is_short=True)
        if success:
            db.log_question(data['question'], type="short")
            logging.info("Short Process Executed 100%.")

def build_community_poll(db, yt_client):
    logging.info("--- [ENGINE] Generating Poll to Hunt Subscribers ---")
    recent_shorts = db.get_past_questions(days=7)
    if recent_shorts:
         poll_question = random.choice(recent_shorts)
         success = yt_client.create_community_post(poll_question)
         logging.info(f"Poll generation triggered. Result: {success}")

def autonomous_run(override=None):
    db = DatabaseManager("database/brain_memory.json")
    ai = GenerativeAI()
    video_sys = VideoDirector()
    yt = YouTubeClient(token_index=1)
    
    action = override
    if not action or action == "":
        chance = random.random()
        # Strategy probability simulator. Hits short approx 4x a day from crons
        if chance < 0.65:
            action = "short"
        elif chance < 0.80:
            action = "poll"
        else:
            action = "manager"
            
    if action == "short":
        build_short_video(db, ai, video_sys, yt)
    elif action == "long":
        logging.info("Executing Weekly Long Video Mode")
        # Extend script x20, longer process
        data_list =[ai.generate_quiz_script(db) for _ in range(10)]
        path, meta = video_sys.create_masterpiece(data_list, type="long")
        if path: yt.upload_video(path, ai.generate_seo_metadata({"questions": "mix"}, is_long=True), is_short=False)
    elif action == "poll":
        build_community_poll(db, yt)
    elif action == "manager":
        logging.info("[MANAGER] Deep Analytics Update executing... Adapting DB.")
        db.cleanup_memory()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Self-Governing Engine")
    parser.add_argument("cmd", choices=["run-auto", "force-short", "force-long", "test"])
    parser.add_argument("--override", type=str, default="", help="Force command override from CI")
    args = parser.parse_args()
    
    if args.cmd == "run-auto":
        autonomous_run(args.override)
    elif args.cmd == "force-short":
         autonomous_run("short")
