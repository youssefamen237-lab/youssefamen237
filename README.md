# YouTube Autopilot (GitHub Actions) — Shorts + Longs (English)

This repository is a **100% automated** YouTube publishing system that runs on **GitHub Actions**.

It generates:
- **Shorts:** ~4/day (with occasional 3 or 5 to avoid a “bot pattern”)
- **Long videos:** ~4/week (quiz compilations, 5–10+ minutes)

It includes:
- Template rotation (8+ templates)
- Anti-duplicate logic (no “same idea” within 15 days)
- Multi-voice rotation (with data-driven weighting)
- Background/music rotation with graceful fallback
- Match prediction template (big matches only) via football fixtures APIs
- Daily analyst (updates best posting times, templates, voices, topics)

> ⚠️ Important: This code is written to be resilient and production-ready, but **you are responsible** for ensuring you have the right to use any assets (backgrounds/music) and that your API usage complies with each provider’s Terms.

---

## 1) Required GitHub Secrets

You already have most of these. The workflows use:

### YouTube Upload (OAuth)
- `YT_CLIENT_ID_1`
- `YT_CLIENT_SECRET_1`
- `YT_REFRESH_TOKEN_1`
- `YT_CHANNEL_ID` (optional but recommended)

### YouTube Analytics (separate OAuth profile, optional but recommended)
- `YT_CLIENT_ID_3`
- `YT_CLIENT_SECRET_3`
- `YT_REFRESH_TOKEN_3`

### Sports fixtures (optional)
- `FOOTBALL_DATA_TOKEN` (football-data.org)
- `API_FOOTBALL_KEY` (API-Football)

### Voice (optional but recommended)
- `ELEVEN_API_KEY` (ElevenLabs)

Optional (used only as fallback / enrichment):
- `OPENAI_API_KEY`

---

## 2) How it runs

### Bootstrap (first real upload)
Run the **Bootstrap** workflow:
- Creates **1 real Short** (immediate publish)
- Creates **1 real Long** (immediate publish)

### Daily
The **Daily** workflow:
- Runs once per day (cron)
- Runs the **analyst**
- Generates today's plan
- Uploads and schedules today's Shorts (and Long if due)

---

## 3) Repository layout

- `.github/workflows/` → GitHub Actions workflows
- `autoyt/` → Python package (pipeline, rendering, analytics)
- `config/` → static config + dynamic state
- `assets/backgrounds/` → optional local backgrounds
- `assets/music/` → optional local music
- `data/` → logs + history (committed by Actions)

---

## 4) Notes & Safety

- Content is **English only**.
- Safety filter blocks politics/religion/sexual/hate topics.
- Questions are **data-driven** from a country dataset (RestCountries API with caching). If the API fails, a small built-in fallback dataset is used to avoid stopping the pipeline.

---

## 5) Local run (optional)

```bash
python -m autoyt.cli bootstrap --shorts 1 --longs 1 --publish-now
python -m autoyt.cli daily
python -m autoyt.cli analyst
```

---

## 6) Customize

Edit:
- `config/base_config.json` (static defaults)
- `config/state.json` (auto-updated by analyst)

Add your own assets:
- `assets/backgrounds/*.jpg|png`
- `assets/music/*.mp3|wav`

