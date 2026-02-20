# Autonomous YouTube AI System

GitHub Actions-native autonomous system for generating, rendering, optimizing, and uploading YouTube Shorts and Long videos.

## Runtime
- Python 3.11
- FFmpeg
- YouTube Data API v3
- Multi-provider LLM + TTS fallbacks

## Workflow
- Single master workflow: `.github/workflows/autonomous-ops.yml`
- Runs on cron and workflow_dispatch
- Bootstraps first Short + first Long automatically
- Continues autonomous generation, upload, analytics, and recovery

## Required Secrets
Add all API secrets referenced in `project_spec.md`.
