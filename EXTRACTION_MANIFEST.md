# Extraction Complete — File Manifest

All 106 files extracted across Batches 1–10.

## Post-extraction setup (run once from repo root)
```bash
bash create_init_files.sh          # creates 20 empty __init__.py packages
pip install -r requirements.txt    # install all Python dependencies
# On GitHub Actions: ffmpeg + fonts-dejavu-core installed via apt in daily_production.yml
```

## Then run in Supabase SQL editor:
```
data/schemas/supabase_schema.sql   # creates all 15 tables, views, functions, seed data
```

## Then configure GitHub Secrets (see README.md for full list), then:
```
Actions → Bootstrap Seed Data → Run workflow
```
---

## Batch Manifest

### Batch 1 — Config & Schema (5 files)
- requirements.txt
- .gitignore
- CHANNEL_CONSTITUTION.md
- README.md
- data/schemas/supabase_schema.sql

### Batch 2 — Storage Layer (5 files)
- storage/supabase_client.py
- storage/redis_client.py
- storage/r2_client.py
- storage/cleanup_manager.py
- create_init_files.sh  ← run this first

### Batch 3 — Cascade Base + LLM (8 files)
- cascade/base_provider.py
- cascade/cascade_manager.py
- cascade/llm/gemini_provider.py
- cascade/llm/groq_provider.py
- cascade/llm/openrouter_provider.py
- cascade/llm/together_provider.py
- cascade/llm/openai_provider.py
- cascade/llm/llm_cascade.py

### Batch 4 — TTS + Footage Cascades (11 files)
- cascade/tts/elevenlabs_key1_provider.py
- cascade/tts/elevenlabs_key2_provider.py
- cascade/tts/elevenlabs_key3_provider.py
- cascade/tts/edge_tts_provider.py
- cascade/tts/tts_cascade.py
- cascade/footage/pexels_video_provider.py
- cascade/footage/pixabay_video_provider.py
- cascade/footage/coverr_provider.py
- cascade/footage/internet_archive_provider.py
- cascade/footage/vecteezy_provider.py
- cascade/footage/footage_cascade.py

### Batch 5 — Image + AI-Image Cascades (10 files)
- cascade/images/unsplash_provider.py
- cascade/images/pexels_photo_provider.py
- cascade/images/pixabay_photo_provider.py
- cascade/images/freepik_provider.py
- cascade/images/image_cascade.py
- cascade/ai_images/getimg_provider.py
- cascade/ai_images/stability_provider.py
- cascade/ai_images/dezgo_provider.py
- cascade/ai_images/ai_horde_provider.py
- cascade/ai_images/ai_images_cascade.py

### Batch 6 — Production Engines Part 1 (8 files)
- engines/topic_selector.py
- engines/fact_research.py
- engines/script_writer.py
- engines/voice_generator.py
- engines/media_fetcher.py
- engines/subtitle_engine.py
- engines/image_processor.py
- engines/video_assembler.py

### Batch 7 — Production Engines Part 2 + Intelligence (7 files)
- engines/metadata_generator.py
- engines/quality_gate.py
- engines/thumbnail_generator.py
- engines/publisher.py
- intelligence/hook_selector.py
- intelligence/story_flow.py
- intelligence/music_selector.py

### Batch 8 — Protection Layer + YouTube Upload (9 files)
- protection/duplicate_guard.py
- protection/fact_verifier.py
- protection/visual_verifier.py
- protection/copyright_checker.py
- protection/policy_guard.py
- youtube/upload/quota_manager.py
- youtube/upload/key_rotator.py
- youtube/upload/upload_client.py
- youtube/upload/upload_scheduler.py

### Batch 9 — YouTube Management + Pipelines + Analytics (7 files)
- youtube/management/management_client.py
- youtube/management/analytics_puller.py
- pipelines/short_pipeline.py
- pipelines/longform_pipeline.py
- pipelines/batch_runner.py
- analytics/performance_analyzer.py
- analytics/competitor_tracker.py

### Batch 10 — Channel OS + Reporting + Seeds + Bootstrap + Workflows (16 files)
- channel_os/portfolio_manager.py
- channel_os/growth_manager.py
- channel_os/cos.py
- channel_os/monetization_tracker.py
- reporting/daily_dashboard.py
- data/seeds/seed_topics.py
- data/seeds/seed_music.py
- bootstrap/initial_setup.py
- .github/workflows/bootstrap_seed.yml
- .github/workflows/daily_production.yml
- .github/workflows/daily_publishing.yml
- .github/workflows/storage_cleanup.yml
- .github/workflows/queue_health_check.yml
- .github/workflows/analytics_daily.yml
- .github/workflows/cos_weekly_review.yml
- .github/workflows/status_report.yml

### __init__.py files (20 packages — all empty, created by create_init_files.sh)
analytics/ bootstrap/ cascade/ cascade/ai_images/ cascade/footage/
cascade/images/ cascade/llm/ cascade/tts/ channel_os/ data/ data/seeds/
engines/ intelligence/ pipelines/ protection/ reporting/ storage/
youtube/ youtube/management/ youtube/upload/
