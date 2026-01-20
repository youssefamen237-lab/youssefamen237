# Automated YouTube Trivia Channel (GitHub Actions)

This repo runs a fully automated, data-driven trivia channel:

- 4 YouTube Shorts per day (spaced + jitter)
- 3 Long-form videos per week (new content, not Shorts compilations)
- Question bank is dataset-driven (CSV in `question_bank/datasets/`)
- 100% automated via `.github/workflows/daily.yml`

## Quick start

1. Add the required secrets in GitHub:
   - `YT_CLIENT_ID_1`, `YT_CLIENT_SECRET_1`, `YT_REFRESH_TOKEN_1`, `YT_CHANNEL_ID`
2. (Optional) Add free asset keys:
   - `PEXELS_API_KEY`, `FREESOUND_API`
3. Push to `main` and enable Actions.
4. Run the workflow manually once (`workflow_dispatch`) to trigger the first upload.

## Add your own assets

- Background images: `assets/backgrounds/` or `user_assets/backgrounds/`
- Music: `assets/music/` or `user_assets/music/`

If folders are empty, the pipeline generates safe local fallbacks automatically.
