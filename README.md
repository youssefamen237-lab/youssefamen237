# 🧠 Quizzaro — Automated YouTube Shorts Channel

> **100% cloud-automated trivia & quiz Shorts channel running on GitHub Actions.**
> Zero local execution. Zero paid infrastructure. Fully production-ready.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [Setup & Deployment](#setup--deployment)
- [Environment Secrets](#environment-secrets)
- [Workflow Schedule](#workflow-schedule)
- [The 8 Video Templates](#the-8-video-templates)
- [Anti-Duplicate System](#anti-duplicate-system)
- [Strategy Optimizer](#strategy-optimizer)
- [Community Polls Engine](#community-polls-engine)
- [Human-Touch Layer](#human-touch-layer)
- [Data Persistence](#data-persistence)
- [Monetisation Tracking](#monetisation-tracking)

---

## Overview

Quizzaro is an end-to-end automated YouTube Shorts channel that:

- **Generates** trivia questions using free AI APIs (Gemini → Groq → OpenRouter)
- **Renders** 1080×1920 Shorts at 30fps with animated text, circular timer, and phosphor-green answer reveal
- **Uploads** 4–8 Shorts daily on a randomised schedule
- **Posts** 1–4 community polls daily to drive engagement
- **Analyses** weekly performance and auto-updates strategy with no human input
- **Targets** English-speaking audiences (US, UK, CA, AU) for monetisation

**Monetisation targets:** 1,000 subscribers + 4,000 watch-hours (tracked automatically)

---

## Project Structure

```
quizzaro/
│
├── .github/workflows/
│   ├── bootstrap.yml          # Manual: first-run, publishes 1 Short immediately
│   ├── daily_publish.yml      # Daily 05:00 UTC: produce & upload 4–8 Shorts
│   ├── polls_publisher.yml    # Daily 08:00 UTC: post 1–4 community polls
│   └── project_manager.yml   # Monday 03:00 UTC: analytics + strategy update
│
├── audio/
│   ├── audio_engine.py        # Top-level audio coordinator
│   ├── tts_engine.py          # EdgeTTS → Kokoro ONNX → Bark fallback chain
│   ├── voice_humanizer.py     # ±2% speed/pitch randomisation
│   └── sfx_manager.py        # Freesound CC0 SFX cache (tick-tock, ding, whoosh)
│
├── core/
│   ├── content_engine.py      # Question generation + 20 categories + CTA variants
│   ├── ai_engine.py           # Gemini → Groq → OpenRouter dispatcher
│   ├── content_fetcher.py     # Wikipedia + Google Trends + NewsAPI + YouTube
│   ├── question_bank.py       # Orchestrator: wires AI + fetcher + anti-duplicate
│   └── anti_duplicate.py     # TinyDB: 15d questions / 10d backgrounds / 7d music
│
├── manager/
│   ├── project_manager.py     # Weekly analytics orchestrator
│   ├── analytics_fetcher.py   # All YouTube Data + Analytics API calls
│   └── strategy_optimizer.py # Scoring → ranking → strategy_config.json updater
│
├── publishing/
│   ├── youtube_uploader.py    # OAuth2 + resumable upload + quota tracker
│   ├── polls_engine.py        # Community polls: rephrasing + anti-duplicate
│   ├── metadata_generator.py  # AI SEO titles + 10 fallback templates
│   └── scheduler.py          # Randomised publish times with 45-min min gap
│
├── templates/
│   ├── __init__.py            # Template dispatcher (name → module)
│   ├── true_false.py          # TRUE / FALSE two-button layout
│   ├── multiple_choice.py     # A / B / C / D option buttons
│   ├── direct_question.py     # Open question, no options shown
│   ├── guess_answer.py        # Blanked answer with typewriter reveal
│   ├── quick_challenge.py     # High-energy pulsing badge, 5-second urgency
│   ├── only_geniuses.py       # Prestige purple/gold ego-bait format
│   ├── memory_test.py         # Memorise → hide → question sequence
│   └── visual_question.py    # Spotlight vignette + frosted card layout
│
├── utils/
│   ├── secrets_loader.py      # Validates & loads all 45 env secrets
│   ├── logger.py              # Loguru: coloured stdout + rotating file log
│   ├── fallback_manager.py    # Tracks failed providers per-run
│   └── rate_limiter.py       # Token-bucket per-API rate limiting
│
├── video/
│   ├── video_composer.py      # Master pipeline: BG → TTS → BGM → frames → FFmpeg
│   ├── video_renderer.py      # Low-level frame rendering helpers
│   ├── template_engine.py     # Weighted template rotation with streak prevention
│   ├── text_animator.py       # Cubic ease-out pop-up animation
│   ├── timer_renderer.py      # Programmatic circular countdown arc
│   ├── background_manager.py  # Pexels → Pixabay → gradient fallback + blur
│   ├── music_engine.py        # Freesound CC0 BGM + random slice
│   └── watermark.py          # Horizontal drift + sine wave @Quizzaro_1
│
├── data/
│   └── init_data.py           # Initialises all JSON files + downloads fonts
│
├── main.py                    # CLI entry point (--mode publish/polls/manager/bootstrap)
├── requirements.txt           # All Python dependencies
└── README.md                  # This file
```

---

## How It Works

### Short Production Pipeline

```
QuestionBank.get_next_question()
    └── ContentFetcher (Wikipedia / Trends / News)
    └── AIEngine.generate_json() [Gemini → Groq → OpenRouter]
    └── AntiDuplicate.is_question_used() [15-day SHA-256 check]

VideoComposer.render_short(question)
    ├── TemplateEngine.pick_template()     [weighted rotation, 8 templates]
    ├── BackgroundManager.get_frames()     [Pexels → Pixabay → gradient]
    ├── AudioEngine.render_question_audio() [TTS + ±2% humanisation]
    ├── MusicEngine.get_bgm()              [Freesound CC0 + random slice]
    ├── Frame loop (30fps):
    │     Phase 1: Question + pop-up animation + CTA [≈4s]
    │     Phase 2: Circular countdown timer          [5s]
    │     Phase 3: Phosphor-green answer reveal      [5s]
    │     Each frame: WatermarkEngine.apply()
    └── FFmpeg: frames + mixed audio → final_short.mp4

YouTubeUploader.upload_with_metadata()
    └── Resumable upload + scheduled publish_at
    └── PublishLog.append()
```

### Video Anatomy

| Phase | Duration | What Happens |
|---|---|---|
| Question | 3–5.5s | Pop-up animated question, CTA text, template-specific options |
| Timer | 5s | Circular arc green→amber→red, tick-tock SFX, digit countdown |
| Answer | 5s | Phosphor-green glow reveal + ding/whoosh SFX + explanation |

---

## Setup & Deployment

### 1. Fork / clone this repository

```bash
git clone https://github.com/YOUR_USERNAME/quizzaro.git
cd quizzaro
```

### 2. Add all 45 secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**
and add every key listed in the [Environment Secrets](#environment-secrets) section below.

### 3. Obtain YouTube OAuth2 credentials (×3 sets)

You need **3 separate OAuth2 credential sets** from [Google Cloud Console](https://console.cloud.google.com):

| Credential Set | Used for | Scope needed |
|---|---|---|
| `YT_CLIENT_ID_1` + `SECRET_1` + `REFRESH_TOKEN_1` | Uploading Shorts | `youtube.upload` |
| `YT_CLIENT_ID_2` + `SECRET_2` + `REFRESH_TOKEN_2` | Community polls | `youtube.force-ssl` |
| `YT_CLIENT_ID_3` + `SECRET_3` + `REFRESH_TOKEN_3` | Analytics read | `yt-analytics.readonly` |

To generate a refresh token:
```bash
pip install google-auth-oauthlib
python -c "
from google_auth_oauthlib.flow import InstalledAppFlow
flow = InstalledAppFlow.from_client_secrets_file('client_secret.json',
    scopes=['https://www.googleapis.com/auth/youtube.upload'])
creds = flow.run_local_server()
print('REFRESH TOKEN:', creds.refresh_token)
"
```

### 4. Run Bootstrap (first time only)

Go to **Actions → 🚀 Bootstrap → Run workflow**

This will:
1. Initialise all data files and download fonts
2. Generate and upload your **first Short immediately** (public)
3. All subsequent workflows run on schedule automatically

---

## Environment Secrets

All 45 secrets must be added to GitHub → Settings → Secrets:

```
GEMINI_API_KEY          GROQ_API_KEY            OPENAI_API_KEY
OPENROUTER_KEY          HF_API_TOKEN            PEXELS_API_KEY
PIXABAY_API_KEY         FREESOUND_API           FREESOUND_ID
NEWS_API                YOUTUBE_API_KEY         YT_CHANNEL_ID
YT_CLIENT_ID_1          YT_CLIENT_SECRET_1      YT_REFRESH_TOKEN_1
YT_CLIENT_ID_2          YT_CLIENT_SECRET_2      YT_REFRESH_TOKEN_2
YT_CLIENT_ID_3          YT_CLIENT_SECRET_3      YT_REFRESH_TOKEN_3
SERPAPI                 TAVILY_API_KEY          NASA_API_KEY
NOAA_API_KEY            REPLICATE_API_TOKEN     ASSEMBLYAI
ELEVEN_API_KEY          CAMB_AI_KEY_1           GETIMG_API_KEY
REMOVE_BG_API           FREEPIK_API_KEY         UNSPLASH_ACCESS_KEY
UNSPLASH_ID             UNSPLASH_SECRET_KEY     VECTEEZY_ID
VECTEEZY_SECRET_KEY     COVERR_API_ID           COVERR_API_KEY
INTERNET_ARCHIVE_ACCESS_KEY                     INTERNET_ARCHIVE_SECRET_KEY
API_FOOTBALL_KEY        FOOTBALL_DATA_ORG       FOOTBALL_DATA_TOKEN
ZENSERP
```

> **Minimum required for core function:** `GEMINI_API_KEY` or `GROQ_API_KEY`,
> `PEXELS_API_KEY`, `FREESOUND_API`, `FREESOUND_ID`, `YOUTUBE_API_KEY`,
> `YT_CHANNEL_ID`, and all three OAuth2 credential sets.

---

## Workflow Schedule

| Workflow | Trigger | Action |
|---|---|---|
| `bootstrap.yml` | Manual (once) | Init data + publish 1 Short NOW |
| `daily_publish.yml` | Daily **05:00 UTC** | Produce & upload 4–8 Shorts |
| `polls_publisher.yml` | Daily **08:00 UTC** | Post 1–4 community polls |
| `project_manager.yml` | **Monday 03:00 UTC** | Analytics + strategy update |

All workflows also support `workflow_dispatch` for manual triggering.

---

## The 8 Video Templates

Each template has a unique badge, colour palette, and interaction hook:

| Template | Badge | Hook |
|---|---|---|
| `true_false` | "TRUE OR FALSE?" — yellow | Two large clickable buttons |
| `multiple_choice` | "MULTIPLE CHOICE" — purple | 4 coloured A/B/C/D option pills |
| `direct_question` | "QUICK QUESTION" — blue | Open-ended, drives comments |
| `guess_answer` | "GUESS THE ANSWER" — orange | Blanked answer + typewriter reveal |
| `quick_challenge` | "⚡ QUICK CHALLENGE" — red/orange | Pulsing badge, urgency cues |
| `only_geniuses` | "🧠 ONLY GENIUSES" — purple/gold | Star rating, ego-bait engagement |
| `memory_test` | "🔁 MEMORY TEST" — cyan | Show fact → hide → question |
| `visual_question` | "👁 VISUAL QUIZ" — pink/rose | Spotlight vignette on background |

Templates are selected by weighted rotation. Top performers (from analytics)
get 3× weight; underperformers get 0.3× weight. No template appears more
than twice in every 8 consecutive videos.

---

## Anti-Duplicate System

All deduplication is handled by `core/anti_duplicate.py` using TinyDB with SHA-256 fingerprints:

| Resource | Rule | Storage key |
|---|---|---|
| Questions | No repeat for **15 days** | `questions` table |
| Background videos | No repeat for **10 days** | `backgrounds` table |
| Music tracks | No repeat for **7 days** | `music` table |

---

## Strategy Optimizer

Runs every Monday via `project_manager.yml`. Reads 28 days of YouTube Analytics
and updates `data/strategy_config.json` automatically:

**Performance score formula:**
```
score = views×1.0 + avg_view_percent×50 + subs_gained×100 + likes×2 + comments×3
```

**Auto-adjustments:**
- Top 4 templates → 3× weight boost
- Top 6 categories → prioritised in question generation
- Voice gender → male/female/mixed based on >30% performance gap
- Publish hour windows → clusters of best-performing UTC hours
- Video duration → best-performing 2-second bucket ±1.5s
- Daily video count → scales 4–8 based on engagement rate
- Top audiences → derived from geographic analytics (ISO country → audience label)

---

## Community Polls Engine

Runs daily at 08:00 UTC. Takes Shorts published **6–10 days ago** from
`publish_log.json`, rephrases them into poll questions using AI, and posts
them to the YouTube Community tab.

**Why it works:**
- Polls show in subscribers' feeds → drives views on existing Shorts
- Non-subscribers who vote get recommended the channel's content
- YouTube algorithm rewards community engagement with wider distribution

---

## Human-Touch Layer

Every mechanism to prevent bot detection and copyright issues:

| Mechanism | Implementation |
|---|---|
| **Voice fingerprint** | ±2% speed + ±0.5 semitone pitch shift per video |
| **Duration jitter** | ±1.5s random total duration (e.g. 13.2s, 14.7s, 12.9s) |
| **Moving watermark** | @Quizzaro_1 at 30% opacity, horizontal drift + sine wave |
| **Music anti-ContentID** | Random slice from each BGM track, fade in/out |
| **Publish time variation** | ±4 min jitter on every scheduled time |
| **Template rotation** | Streak prevention: no template used >2× in 8 videos |
| **Voice gender rotation** | Random male/female per video |
| **Description variation** | 8 openers × 6 closers × 5 CTA phrases = 240 combos |

---

## Data Persistence

Data is persisted across GitHub Actions runs via `actions/cache@v4`:

```
data/
├── anti_duplicate.json   # TinyDB: question/background/music fingerprints
├── publish_log.json      # All uploaded Shorts with full metadata
├── quota_log.json        # Daily YouTube API quota tracker (9,000 unit limit)
├── polls_log.json        # SHA-256 fingerprints of posted polls
├── strategy_config.json  # Auto-updated strategy (read by all modules)
├── sfx_cache/            # Downloaded SFX files (tick-tock, ding, whoosh)
├── fonts/                # Montserrat font family
├── reports/              # Weekly Markdown analytics reports
└── logs/                 # Rotating log files (7-day retention)
```

---

## Monetisation Tracking

The weekly report (written to `data/reports/report_YYYY-MM-DD.md` and
uploaded as a GitHub Actions artifact) shows:

```
💰 Monetisation Progress
  Subscribers : 423 / 1,000  (42.3%)
  Watch Hours : 1,840 / 4,000 h  (46.0%)
```

Progress is also written to `strategy_config.json` so every module
can access it. The daily video count scales up automatically as the
channel approaches monetisation thresholds.

---

## License

This project is released for private use. All generated content is original.
Background videos are sourced from Pexels / Pixabay (CC0).
Music and SFX are sourced from Freesound (CC0).
TTS voices use Microsoft Edge Neural (free tier) and open-source models.

---

*Built with ❤️ — 100% automated, 100% free-tier APIs, 100% Shorts.*
