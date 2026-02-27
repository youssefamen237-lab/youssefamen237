"""
long_runner.py
Weekly pipeline: produces and uploads one long-form video (~5-8 minutes).
"The Hardest 50 Quiz Questions of the Week"
Uses dynamic B-roll, trivia, motivational checkpoints.
"""

import os
import json
import random
import datetime
import tempfile
import traceback

from content_generator import (
    generate_question, generate_long_video_script,
    TEMPLATES, QUESTION_CATEGORIES
)
from tts_engine import get_consistent_voice
from asset_fetcher import fetch_background_video, fetch_background_image
from long_video_composer import compose_long_video
from video_composer import generate_thumbnail
from youtube_uploader import upload_video
from project_manager import get_current_strategy

VIDEOS_LOG = "data/videos_log.json"
LONG_QUESTIONS_COUNT = 50

LONG_VIDEO_TITLES = [
    "99% of People Fail This Quiz — 50 Questions That Will Break Your Brain!",
    "The Hardest 50 General Knowledge Questions of 2026 — Are You Smart Enough?",
    "Only Geniuses Get 40/50 on This Quiz Challenge — Prove Them Wrong!",
    "50 Trivia Questions That Destroyed the Internet — Can YOU Answer Them?",
    "Ultimate Brain Test: 50 Questions in 5 Minutes — Quiz Plus Weekly Challenge",
    "This Quiz Separated Geniuses From Everyone Else — 50 Questions Inside",
    "50 Questions That Will Test Your IQ — From Easy to Absolutely Brutal",
    "The Weekly Genius Test: 50 Quiz Questions You Must Answer RIGHT NOW",
]

LONG_VIDEO_DESCRIPTIONS = [
    "Think you're smarter than average? Test yourself with our weekly 50-question ultimate quiz challenge! From general knowledge to science, history, and pop culture — this is the hardest quiz of the week. Drop your score in the comments below! Subscribe for daily quiz challenges and weekly masterclasses. 🎯",
    "Welcome to Quiz Plus Weekly! Every week we challenge you with 50 brain-crushing questions. Science, history, geography, pop culture — no topic is safe. Comment your final score and subscribe for daily Shorts quizzes! Only true geniuses finish this. 🧠",
    "How smart are you REALLY? This week's 50-question challenge covers everything from ancient history to modern science. Pause if you have to — but no Googling allowed! Drop your score below and challenge your friends. Subscribe for Quiz Plus daily content! 🎓",
]


def _load_videos_log() -> list:
    if os.path.exists(VIDEOS_LOG):
        with open(VIDEOS_LOG, "r") as f:
            return json.load(f)
    return []


def _save_videos_log(log: list):
    os.makedirs(os.path.dirname(VIDEOS_LOG), exist_ok=True)
    with open(VIDEOS_LOG, "w") as f:
        json.dump(log, f, indent=2)


def _generate_50_questions(strategy: dict) -> list:
    """Generates 50 non-duplicate questions across varied templates and categories."""
    questions = []
    templates_cycle = (strategy.get("best_templates", TEMPLATES) * 10)[:50]
    categories_cycle = (strategy.get("best_categories", QUESTION_CATEGORIES) * 10)[:50]
    random.shuffle(templates_cycle)
    random.shuffle(categories_cycle)

    for i in range(LONG_VIDEO_QUESTIONS_COUNT):
        template = templates_cycle[i % len(templates_cycle)]
        category = categories_cycle[i % len(categories_cycle)]
        for attempt in range(5):
            try:
                q = generate_question(template=template, category=category)
                questions.append(q)
                print(f"[LongRunner] Generated question {len(questions)}/50: {q['question'][:50]}...")
                break
            except Exception as e:
                if attempt == 4:
                    print(f"[LongRunner] Giving up on question {i+1}: {e}")
                    # Use placeholder
                    questions.append({
                        "question": f"What is the capital of France?",
                        "answer": "Paris",
                        "trivia": "Paris has been the French capital for over 1,000 years.",
                        "template": "Direct Question",
                        "category": "geography",
                        "choices": [],
                    })
                continue

    return questions[:50]


LONG_VIDEO_QUESTIONS_COUNT = 50


def run_weekly_long_video():
    """
    Main entry point. Produces and uploads one long-form video.
    """
    print(f"\n{'='*60}")
    print(f"[LongRunner] Weekly Long Video Run - {datetime.datetime.utcnow().isoformat()}")
    print(f"{'='*60}")

    strategy = get_current_strategy()
    videos_log = _load_videos_log()
    work_dir = tempfile.mkdtemp(prefix="long_video_")

    try:
        # 1. Generate 50 questions
        print("[LongRunner] Generating 50 questions...")
        questions = _generate_50_questions(strategy)
        print(f"[LongRunner] Generated {len(questions)} questions.")

        # 2. Compose video
        print("[LongRunner] Composing long video (this takes a few minutes)...")
        video_path = os.path.join(work_dir, "long_video.mp4")
        compose_long_video(questions=questions, output_path=video_path)

        # 3. Generate thumbnail
        thumb_path = os.path.join(work_dir, "thumbnail.jpg")
        bg_img = fetch_background_image(category="abstract colorful knowledge")
        generate_thumbnail(
            question="The Hardest 50 Questions of 2026",
            template="Weekly Masterclass",
            bg_image_path=bg_img,
            output_path=thumb_path,
        )

        # 4. Pick title and description (varied)
        title = random.choice(LONG_VIDEO_TITLES)
        description = random.choice(LONG_VIDEO_DESCRIPTIONS)

        # 5. Build tags
        all_categories = list(set([q.get("category", "quiz") for q in questions]))
        tags = (
            ["quiz", "trivia", "brain test", "general knowledge", "challenge",
             "quiz 2026", "hardest quiz", "genius test", "knowledge test",
             "quiz plus", "viral quiz", "iq test"] +
            all_categories[:5]
        )
        tags = list(set(tags))[:15]

        # 6. Upload
        print(f"[LongRunner] Uploading: {title[:60]}...")
        video_id = upload_video(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            category_id="22",
            privacy="public",
            is_short=False,
            thumbnail_path=thumb_path,
            credential_set=1,
        )

        # 7. Log
        record = {
            "video_id": video_id,
            "type": "long",
            "title": title,
            "question_count": len(questions),
            "categories": all_categories,
            "tags": tags,
            "posted_at": datetime.datetime.utcnow().isoformat(),
            "posted_hour": datetime.datetime.utcnow().hour,
        }
        videos_log.append(record)
        _save_videos_log(videos_log)

        print(f"[LongRunner] ✅ Long video uploaded: https://youtu.be/{video_id}")

    except Exception as e:
        print(f"[LongRunner] ❌ Failed: {e}")
        print(traceback.format_exc())
        error_record = {
            "type": "long_error",
            "error": str(e),
            "traceback": traceback.format_exc(),
            "date": datetime.datetime.utcnow().isoformat(),
        }
        videos_log.append(error_record)
        _save_videos_log(videos_log)
        raise
    finally:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    run_weekly_long_video()
