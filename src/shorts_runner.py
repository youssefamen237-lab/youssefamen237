"""
shorts_runner.py
Daily pipeline: generates and uploads 4 YouTube Shorts.
Reads strategy from project_manager.py.
Logs all metadata to data/videos_log.json for analytics.
Self-healing: fallback at every step.
"""

import os
import json
import random
import datetime
import tempfile
import traceback

from content_generator import (
    generate_question, generate_short_metadata, get_random_cta,
    get_next_template_rotation, TEMPLATES, QUESTION_CATEGORIES
)
from tts_engine import generate_speech, get_consistent_voice
from asset_fetcher import (
    fetch_background_video, fetch_background_image,
    fetch_sfx, fetch_background_music
)
from video_composer import compose_short, generate_thumbnail
from youtube_uploader import upload_video
from project_manager import get_current_strategy

VIDEOS_LOG = "data/videos_log.json"
SHORTS_PER_DAY = 4


def _load_videos_log() -> list:
    if os.path.exists(VIDEOS_LOG):
        with open(VIDEOS_LOG, "r") as f:
            return json.load(f)
    return []


def _save_videos_log(log: list):
    os.makedirs(os.path.dirname(VIDEOS_LOG), exist_ok=True)
    with open(VIDEOS_LOG, "w") as f:
        json.dump(log, f, indent=2)


def _get_last_templates(videos_log: list, n: int = 3) -> list:
    shorts = [v for v in videos_log if v.get("type") == "short"]
    recent = shorts[-n:] if len(shorts) >= n else shorts
    return [v.get("template", "") for v in recent]


def produce_one_short(short_number: int, strategy: dict, videos_log: list) -> dict:
    """
    Produces one complete YouTube Short.
    Returns metadata dict for logging.
    """
    work_dir = tempfile.mkdtemp(prefix=f"short_{short_number}_")
    print(f"\n[ShortsRunner] === Producing Short {short_number}/{SHORTS_PER_DAY} ===")

    # Pick template (avoid repeating last 3)
    last_templates = _get_last_templates(videos_log)
    best_templates = strategy.get("best_templates", TEMPLATES)
    available_templates = [t for t in best_templates if t not in last_templates[-3:]]
    if not available_templates:
        available_templates = TEMPLATES
    template = random.choice(available_templates)

    # Pick category
    best_cats = strategy.get("best_categories", QUESTION_CATEGORIES)
    avoid_cats = strategy.get("avoid_categories", [])
    available_cats = [c for c in best_cats if c not in avoid_cats]
    if not available_cats:
        available_cats = QUESTION_CATEGORIES
    category = random.choice(available_cats)

    print(f"[ShortsRunner] Template: {template}, Category: {category}")

    # 1. Generate question (with anti-duplicate check)
    q = generate_question(template=template, category=category)
    print(f"[ShortsRunner] Question: {q['question'][:60]}...")

    # 2. Generate metadata
    metadata = generate_short_metadata(q["question"], q["answer"], template)
    title = metadata.get("title", f"Can You Answer This? #{random.randint(1,999)}")
    description = metadata.get("description", "")
    tags = metadata.get("tags", ["quiz", "trivia", "shorts"])
    hashtags = metadata.get("hashtags", ["#Quiz", "#Shorts"])
    description = description + "\n\n" + " ".join(hashtags)

    # 3. Generate CTA
    cta = get_random_cta()

    # 4. TTS - question narration
    voice = strategy.get("best_voice", get_consistent_voice())
    voice_path = os.path.join(work_dir, "voice_question.mp3")
    generate_speech(q["question"], voice_path, voice_override=voice)

    # 5. TTS - CTA
    cta_path = os.path.join(work_dir, "voice_cta.mp3")
    generate_speech(cta, cta_path, voice_override=voice)

    # 6. Fetch assets
    print("[ShortsRunner] Fetching background video...")
    bg_video = fetch_background_video()
    if not bg_video:
        bg_video = fetch_background_image(category=category)

    print("[ShortsRunner] Fetching SFX...")
    tick_sfx = fetch_sfx("tick")
    ding_sfx = fetch_sfx("ding")

    print("[ShortsRunner] Fetching BGM...")
    bgm = fetch_background_music(duration_seconds=30)

    # 7. Compose video
    print("[ShortsRunner] Composing video...")
    video_path = os.path.join(work_dir, f"short_{short_number}.mp4")
    compose_short(
        question=q["question"],
        answer=q["answer"],
        choices=q.get("choices", []),
        template=template,
        bg_video_path=bg_video,
        voice_audio_path=voice_path,
        cta_audio_path=cta_path,
        tick_sfx_path=tick_sfx,
        ding_sfx_path=ding_sfx,
        bgm_path=bgm,
        output_path=video_path,
    )

    # 8. Upload to YouTube
    print(f"[ShortsRunner] Uploading: {title[:50]}")
    video_id = upload_video(
        video_path=video_path,
        title=title,
        description=description,
        tags=tags,
        category_id="22",
        privacy="public",
        is_short=True,
        thumbnail_path=None,
        credential_set=random.choice([1, 2]),
    )

    # 9. Log
    record = {
        "video_id": video_id,
        "type": "short",
        "title": title,
        "question": q["question"],
        "answer": q["answer"],
        "choices": q.get("choices", []),
        "template": template,
        "category": category,
        "cta": cta,
        "cta_style": "challenge" if "challenge" in cta.lower() else "question",
        "tags": tags,
        "posted_at": datetime.datetime.utcnow().isoformat(),
        "posted_hour": datetime.datetime.utcnow().hour,
        "voice": voice,
        "short_number_today": short_number,
    }

    # Cleanup temp dir
    import shutil
    shutil.rmtree(work_dir, ignore_errors=True)

    return record


def run_daily_shorts():
    """
    Main entry point. Produces and uploads 4 Shorts.
    Implements per-short error recovery.
    """
    print(f"\n{'='*60}")
    print(f"[ShortsRunner] Daily Shorts Run - {datetime.datetime.utcnow().isoformat()}")
    print(f"{'='*60}")

    strategy = get_current_strategy()
    videos_log = _load_videos_log()

    successful = 0
    failed = 0

    # Stagger uploads throughout the day (varied timing, not all at once)
    import time
    stagger_seconds = [0, random.randint(1800, 5400), random.randint(7200, 10800), random.randint(14400, 18000)]

    for i in range(SHORTS_PER_DAY):
        # Wait for staggered timing (skip first)
        if i > 0:
            wait = stagger_seconds[i] - stagger_seconds[i-1]
            print(f"[ShortsRunner] Waiting {wait//60} minutes before next short...")
            time.sleep(wait)

        try:
            record = produce_one_short(i + 1, strategy, videos_log)
            videos_log.append(record)
            _save_videos_log(videos_log)
            successful += 1
            print(f"[ShortsRunner] ✅ Short {i+1} done: https://youtu.be/{record['video_id']}")
        except Exception as e:
            failed += 1
            error_record = {
                "type": "short_error",
                "short_number": i + 1,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "date": datetime.datetime.utcnow().isoformat(),
            }
            videos_log.append(error_record)
            _save_videos_log(videos_log)
            print(f"[ShortsRunner] ❌ Short {i+1} failed: {e}")
            print(traceback.format_exc())

    print(f"\n[ShortsRunner] Daily run complete. ✅ {successful} succeeded, ❌ {failed} failed.")


if __name__ == "__main__":
    run_daily_shorts()
