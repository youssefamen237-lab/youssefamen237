# Autonomous YouTube AI System

GitHub Actions-native autonomous system for generating, rendering, optimizing, and uploading YouTube Shorts and Long videos.

## Runtime
- Python 3.11
- FFmpeg
- YouTube Data API v3
- Multi-provider LLM + TTS fallbacks

## Required Secrets
Add all API secrets referenced in `project_spec.md` and at minimum:
- `YT_CLIENT_ID_3`
- `YT_CLIENT_SECRET_3`
- `YT_REFRESH_TOKEN_3`
- `GEMINI_API_KEY`
- `GROQ_API_KEY`
- `OPENROUTER_KEY`
- `ELEVEN_API_KEY` (optional fallback to gTTS if missing)

After secrets are set, workflows run autonomously.
