"""
Long Video Orchestrator — end-to-end pipeline for producing and publishing one Long Video.
Generates 15+ questions, renders compilation, creates thumbnail, SEO, publishes.
"""

import os
import sys
import json
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from content.generator import generate_question_for_video, mark_as_used, INTERNAL_QUESTION_BANK
from video.background import get_background_image
from video.renderer_long import render_long_video, generate_long_video_title
from video.thumbnail import create_long_video_thumbnail
from seo.engine import generate_long_seo
from publisher.youtube import publish_long_video
from utils.dedup import validate_question_data, register_question_published, register_video_published
from utils.rate_limiter import (
    can_upload_long, log_upload_attempt, sanitize_metadata,
    check_video_file, add_jitter_delay
)

OUTPUT_DIR = Path("output/long")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_QUESTIONS = 20  # ~7+ minutes
MIN_QUESTIONS = 15     # minimum for 5+ minutes


def collect_questions(target=TARGET_QUESTIONS):
    """Collect unique, non-duplicate questions for long video"""
    questions = []
    used_questions = set()
    attempts = 0
    max_attempts = target * 3

    while len(questions) < target and attempts < max_attempts:
        attempts += 1
        try:
            q = generate_question_for_video()
            q_text = q.get("question", "")

            if q_text in used_questions:
                continue

            issues = validate_question_data(q)
            # For long videos, template repetition is OK (it's a compilation)
            content_issues = [i for i in issues if "Template" not in i]
            if content_issues:
                continue

            questions.append(q)
            used_questions.add(q_text)
            print(f"[LongOrchestrator] Q{len(questions)}: {q_text[:60]}")

        except Exception as e:
            print(f"[LongOrchestrator] Question gen error: {e}")

    # If we didn't get enough, fill from internal bank
    if len(questions) < MIN_QUESTIONS:
        print(f"[LongOrchestrator] Only {len(questions)} questions, filling from internal bank")
        import random
        bank_copy = list(INTERNAL_QUESTION_BANK)
        random.shuffle(bank_copy)
        for q in bank_copy:
            if q["question"] not in used_questions and len(questions) < target:
                questions.append(q)
                used_questions.add(q["question"])

    print(f"[LongOrchestrator] Collected {len(questions)} questions")
    return questions


def run_long_pipeline(dry_run=False, force=False):
    """
    Full production pipeline for one Long Video.
    dry_run=True: generates video but does not upload.
    force=True: bypass daily/weekly limit checks (for first run or manual trigger).
    """
    print("\n" + "="*60)
    print("  LONG VIDEO PRODUCTION PIPELINE")
    print("="*60)

    # ── Safety check ───────────────────────────────────────────────
    if not force:
        can_post, reason = can_upload_long()
        if not can_post:
            print(f"[LongOrchestrator] Cannot post long video now: {reason}")
            return None
    else:
        print("[LongOrchestrator] Force mode — skipping rate limit check")

    # ── Step 1: Collect Questions ──────────────────────────────────
    print("\n[Step 1/6] Collecting questions...")
    questions = collect_questions(TARGET_QUESTIONS)

    if len(questions) < MIN_QUESTIONS:
        print(f"[LongOrchestrator] Insufficient questions ({len(questions)} < {MIN_QUESTIONS})")
        return None

    # ── Step 2: Generate Title ─────────────────────────────────────
    print("\n[Step 2/6] Generating video title...")
    video_title = generate_long_video_title(len(questions))
    print(f"[LongOrchestrator] Title: {video_title}")

    timestamp = int(time.time())
    work_dir = OUTPUT_DIR / f"long_{timestamp}"
    work_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 3: Fetch Background for Thumbnail ─────────────────────
    print("\n[Step 3/6] Fetching background...")
    bg_path = str(work_dir / "background.jpg")
    try:
        bg_path = get_background_image(bg_path)
    except Exception as e:
        print(f"[LongOrchestrator] Background failed: {e}")
        bg_path = None

    # ── Step 4: Render Long Video ──────────────────────────────────
    print("\n[Step 4/6] Rendering long video (this takes a while)...")
    video_path = str(work_dir / "long_video.mp4")
    try:
        video_path = render_long_video(questions, video_title, video_path)
    except Exception as e:
        print(f"[LongOrchestrator] Video rendering failed: {e}")
        traceback.print_exc()
        return None

    ok, msg = check_video_file(video_path)
    if not ok:
        print(f"[LongOrchestrator] Video validation failed: {msg}")
        return None

    # ── Step 5: Create Thumbnail ───────────────────────────────────
    print("\n[Step 5/6] Creating thumbnail...")
    thumbnail_path = str(work_dir / "thumbnail.jpg")
    try:
        thumbnail_path = create_long_video_thumbnail(video_title, bg_path, thumbnail_path)
    except Exception as e:
        print(f"[LongOrchestrator] Thumbnail failed (non-fatal): {e}")
        thumbnail_path = None

    # ── Step 6: SEO + Publish ──────────────────────────────────────
    print("\n[Step 6/6] Generating SEO and publishing...")
    seo_package = generate_long_seo(questions, video_title)
    seo_package["title"], seo_package["description"], seo_package["tags"] = sanitize_metadata(
        seo_package["title"],
        seo_package["description"],
        seo_package.get("tags", []),
    )

    if dry_run:
        print("[LongOrchestrator] DRY RUN — skipping YouTube upload")
        result = {
            "status": "dry_run",
            "video_path": video_path,
            "thumbnail_path": thumbnail_path,
            "title": seo_package["title"],
            "questions_count": len(questions),
        }
        print(json.dumps(result, indent=2))
        return result

    try:
        add_jitter_delay(base_seconds=15, jitter_seconds=45)
        video_id = publish_long_video(video_path, thumbnail_path, seo_package)

        # Register everything
        for q in questions:
            register_question_published(q)
            mark_as_used(q)
        register_video_published(seo_package["title"], "long")
        log_upload_attempt("long", True, seo_package["title"])

        result = {
            "status": "published",
            "video_id": video_id,
            "url": f"https://youtube.com/watch?v={video_id}",
            "title": seo_package["title"],
            "questions_count": len(questions),
        }
        print(f"\n[LongOrchestrator] ✅ LONG VIDEO PUBLISHED: https://youtube.com/watch?v={video_id}")
        return result

    except Exception as e:
        print(f"[LongOrchestrator] ❌ Publish failed: {e}")
        log_upload_attempt("long", False, seo_package.get("title", ""))
        traceback.print_exc()
        return None


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    result = run_long_pipeline(dry_run=dry, force=force)
    if result:
        print("\n[Done] Long video pipeline completed")
        sys.exit(0)
    else:
        print("\n[Done] Long video pipeline failed")
        sys.exit(1)
