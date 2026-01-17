# YouTube AutoChannel (Data-driven Trivia)

This repo renders and schedules:
- **Shorts:** 4/day (spaced with jitter; never a batch dump)
- **Long-form:** 3/week (16:9; original episode style; not a shorts compilation)

## How it works
- Picks questions from CSV/JSON datasets in `data/`.
- Renders videos with **FFmpeg** (background blur + dark semi-transparent text box).
- Generates **TTS** audio (free providers by default) and mixes quiet background music with ducking.
- Uploads as **Private** and sets **publishAt** to schedule each video.
- Stores metadata + de-dup fingerprints in **SQLite** (`db/state.sqlite`).

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m yt_autochannel.main run
```

## GitHub Actions
- Daily workflow: `.github/workflows/daily.yml`
- Reads secrets from GitHub Environment Secrets.
- Produces run reports as workflow artifacts.

## Environment variables
See `src/yt_autochannel/config.py` for the full config.

Minimum required for uploading:
- `YOUTUBE_API_KEY` (optional, for some endpoints)
- OAuth credentials + refresh token: `YT_CLIENT_ID_1`, `YT_CLIENT_SECRET_1`, `YT_REFRESH_TOKEN_1`, `YT_CHANNEL_ID`

Kill switch:
- `RUN_ENABLED=false`

Dry run:
- `DRY_RUN=true`

## Notes
- This project expects **ffmpeg** and **ffprobe** available on PATH (GitHub hosted runners include them).
- If `assets/backgrounds/` or `assets/music/` are empty, the pipeline will generate safe placeholders.
