# yt-auto-quiz-channel (GitHub Actions + YouTube)

This repo generates and uploads **original quiz videos** (Shorts + long compilations) using GitHub Actions.

## Folders
- `assets/images/` → put your background images here (optional)
- `assets/music/` → put your music files here (optional)
- `data/` → runtime state + SQLite DB (auto-committed by Actions)
- `outputs/` → generated videos (not committed)

## GitHub Secrets (required for uploads)
- `YT_CLIENT_ID_1`
- `YT_CLIENT_SECRET_1`
- `YT_REFRESH_TOKEN_1`
- (optional fallback) `YT_CLIENT_ID_2`, `YT_CLIENT_SECRET_2`, `YT_REFRESH_TOKEN_2`

## GitHub Secrets (recommended for daily analysis)
- `YT_CLIENT_ID_3`
- `YT_CLIENT_SECRET_3` (or `YT_CLIENT_SECRET_1` as fallback)
- `YT_REFRESH_TOKEN_3`

## AI Keys (free-tier supported)
- `GEMINI_API_KEY` (optional)
- `GROQ_API_KEY` (optional)

## Workflows
- `Publish (Auto)` runs every 20 minutes and on push to `main`.
- `Analyze (Daily)` runs daily and updates weights + best hours.

> Note: Always ensure you have rights to use any images/music you add to `assets/`.
