"""
Short Video Orchestrator — end-to-end pipeline for producing and publishing one YouTube Short.
Steps: generate question → fetch background → generate audio → render video → create thumbnail → SEO → publish
"""

import os
import sys
import json
import time
import random
import tempfile
import traceback
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from content.generator import generate_question_for_video, mark_as_used
from audio.tts import generate_full_short_audio
from video.background import get_background_image
from video.renderer_short import render_short_video
from video.thumbnail import create_shorts_thumbnail
from seo.engine import generate_short_seo
from publisher.youtube import publish_short
from utils.dedup import validate_question_data, register_question_published, register_video_published
from utils.rate_limiter import (
    can_upload_short, log_upload_attempt, sanitize_metadata,
    check_video_file, add_jitter_delay
)

OUTPUT_DIR = Path("output/shorts")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_GENERATION_ATTEMPTS = 5


def run_short_pipeline(dry_run=False):
    """
    Full production pipeline for one YouTube Short.
    dry_run=True: generates video but does not upload to YouTube.
    """
    print("\n" + "="*60)
    print("  SHORT VIDEO PRODUCTION PIPELINE")
    print("="*60)

    # ── Safety check ───────────────────────────────────────────────
    can_post, reason = can_upload_short()
    if not can_post:
        print(f"[Orchestrator] Cannot post short now: {reason}")
        return None

    # ── Step 1: Generate Question ──────────────────────────────────
    print("\n[Step 1/7] Generating question...")
    question_data = None
    for attempt in range(MAX_GENERATION_ATTEMPTS):
        try:
            candidate = generate_question_for_video()
            issues = validate_question_data(candidate)
            if not issues:
                question_data = candidate
                break
            else:
                print(f"[Orchestrator] Question validation issues (attempt {attempt+1}): {issues}")
        except Exception as e:
            print(f"[Orchestrator] Question generation failed (attempt {attempt+1}): {e}")

    if not question_data:
        print("[Orchestrator] Could not generate valid question after all attempts")
        return None

    print(f"[Orchestrator] Question: {question_data['question']}")
    print(f"[Orchestrator] Answer: {question_data['answer']}")
    print(f"[Orchestrator] Template: {question_data['template']}")

    timestamp = int(time.time())
    work_dir = OUTPUT_DIR / f"short_{timestamp}"
    work_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 2: Fetch Background ───────────────────────────────────
    print("\n[Step 2/7] Fetching background image...")
    background_path = str(work_dir / "background.jpg")
    try:
        background_path = get_background_image(background_path)
    except Exception as e:
        print(f"[Orchestrator] Background fetch failed: {e}")
        background_path = None

    # ── Step 3: Generate Audio (MANDATORY) ────────────────────────
    print("\n[Step 3/7] Generating audio (mandatory)...")
    try:
        audio_dir = str(work_dir / "audio")
        audio_files = generate_full_short_audio(
            question_data["question"],
            question_data.get("cta", "Drop your answer in the comments before time runs out!"),
            audio_dir,
        )
        question_data["audio_question"] = audio_files.get("question_audio")
        question_data["audio_cta"] = audio_files.get("cta_audio")
        question_data["combined_audio"] = audio_files.get("combined_audio")
        print(f"[Orchestrator] ✓ Audio ready. Combined: {question_data['combined_audio']}")
    except Exception as e:
        print(f"[Orchestrator] ❌ Audio generation failed: {e}")
        # We do NOT publish silent videos
        return None

    # ── Step 4: Render Video ───────────────────────────────────────
    print("\n[Step 4/7] Rendering video...")
    video_path = str(work_dir / "short.mp4")
    try:
        video_path = render_short_video(question_data, background_path, video_path)
    except Exception as e:
        print(f"[Orchestrator] Video rendering failed: {e}")
        traceback.print_exc()
        return None

    # Validate video
    ok, msg = check_video_file(video_path)
    if not ok:
        print(f"[Orchestrator] Video validation failed: {msg}")
        return None

    # ── Step 5: Create Thumbnail ───────────────────────────────────
    print("\n[Step 5/7] Creating thumbnail...")
    thumbnail_path = str(work_dir / "thumbnail.jpg")
    try:
        thumbnail_path = create_shorts_thumbnail(
            question_data["question"],
            question_data.get("template", "Trivia"),
            background_path,
            thumbnail_path,
        )
    except Exception as e:
        print(f"[Orchestrator] Thumbnail creation failed (non-fatal): {e}")
        thumbnail_path = None

    # ── Step 6: Generate SEO ───────────────────────────────────────
    print("\n[Step 6/7] Generating SEO metadata...")
    seo_package = generate_short_seo(question_data)

    # Sanitize metadata
    seo_package["title"], seo_package["description"], seo_package["tags"] = sanitize_metadata(
        seo_package["title"],
        seo_package["description"],
        seo_package.get("tags", []),
    )

    print(f"[Orchestrator] Title: {seo_package['title']}")

    # ── Step 7: Publish ────────────────────────────────────────────
    print("\n[Step 7/7] Publishing to YouTube...")

    if dry_run:
        print("[Orchestrator] DRY RUN — skipping YouTube upload")
        result = {
            "status": "dry_run",
            "video_path": video_path,
            "thumbnail_path": thumbnail_path,
            "question": question_data["question"],
            "title": seo_package["title"],
        }
        print(json.dumps(result, indent=2))
        return result

    try:
        add_jitter_delay(base_seconds=10, jitter_seconds=30)
        video_id = publish_short(video_path, thumbnail_path, seo_package)

        # Register as used
        register_question_published(question_data)
        register_video_published(seo_package["title"], "short")
        mark_as_used(question_data)
        log_upload_attempt("short", True, seo_package["title"])

        result = {
            "status": "published",
            "video_id": video_id,
            "url": f"https://youtube.com/shorts/{video_id}",
            "title": seo_package["title"],
            "question": question_data["question"],
        }
        print(f"\n[Orchestrator] ✅ SHORT PUBLISHED: https://youtube.com/shorts/{video_id}")
        return result

    except Exception as e:
        print(f"[Orchestrator] ❌ Publish failed: {e}")
        log_upload_attempt("short", False, seo_package.get("title", ""))
        traceback.print_exc()
        return None


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    result = run_short_pipeline(dry_run=dry)
    if result:
        print("\n[Done] Pipeline completed successfully")
        sys.exit(0)
    else:
        print("\n[Done] Pipeline failed")
        sys.exit(1)
