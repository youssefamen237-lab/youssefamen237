# 🧠 Self-Governing AI YouTube Channel System

A fully autonomous YouTube channel powered by GitHub Actions.
Publishes **4 Shorts per day** + **4 Long Videos per week** — completely automatically.

---

## 🚀 Quick Setup (5 Minutes)

### Step 1: Fork or Clone This Repository
Push to your GitHub account as a **public or private** repository.

### Step 2: Add GitHub Secrets
Go to **Settings → Secrets and variables → Actions → New repository secret**

Add ALL of the following secrets:

| Secret Name | Description |
|---|---|
| `YT_CLIENT_ID_1` | YouTube OAuth Client ID (primary) |
| `YT_CLIENT_SECRET_1` | YouTube OAuth Client Secret (primary) |
| `YT_REFRESH_TOKEN_1` | YouTube Refresh Token (primary) |
| `YT_CLIENT_ID_2` | YouTube OAuth Client ID (backup) |
| `YT_CLIENT_SECRET_2` | YouTube OAuth Client Secret (backup) |
| `YT_REFRESH_TOKEN_2` | YouTube Refresh Token (backup) |
| `YT_CLIENT_ID_3` | YouTube OAuth Client ID (analytics/manager) |
| `YT_CLIENT_SECRET_3` | YouTube OAuth Client Secret (analytics/manager) |
| `YT_REFRESH_TOKEN_3` | YouTube Refresh Token (analytics/manager) |
| `YT_CHANNEL_ID` | Your YouTube Channel ID (UCxxxxxxxx) |
| `YOUTUBE_API_KEY` | YouTube Data API v3 Key |
| `GEMINI_API_KEY` | Google Gemini API Key (free) |
| `GROQ_API_KEY` | Groq API Key (free) |
| `OPENAI_API_KEY` | OpenAI API Key (optional fallback) |
| `OPENROUTER_KEY` | OpenRouter API Key (free tier) |
| `HF_API_TOKEN` | HuggingFace API Token (free) |
| `ELEVEN_API_KEY` | ElevenLabs API Key (TTS) |
| `CAMB_AI_KEY_1` | CambAI API Key (TTS fallback) |
| `PEXELS_API_KEY` | Pexels API Key (free, backgrounds) |
| `PIXABAY_API_KEY` | Pixabay API Key (free, backgrounds) |
| `UNSPLASH_ACCESS_KEY` | Unsplash Access Key (free, backgrounds) |
| `NASA_API_KEY` | NASA API Key (free, space backgrounds) |

### Step 3: Enable GitHub Actions
Go to **Actions** tab → Click **"I understand my workflows, go ahead and enable them"**

### Step 4: Trigger First Run
Go to **Actions → 🚀 FIRST RUN → Run workflow**

That's it. The system starts immediately and runs forever.

---

## 🔄 How It Works

```
Every Day (4x):
  GitHub Actions Runner →
    Generate unique trivia question (Gemini/Groq/OpenAI) →
    Fetch background image (Pexels/Pixabay/Unsplash/NASA) →
    Generate voice audio (ElevenLabs/CambAI/OpenAI/HuggingFace/gTTS) →
    Render Short video (FFmpeg, 1080×1920) →
    Create thumbnail (Pillow) →
    Generate SEO metadata (AI + templates) →
    Upload to YouTube (OAuth API) →
    Done ✅

Every Mon/Wed/Fri/Sun:
  Same pipeline but with 20 questions compiled →
  5-7 minute Long Video →
  Published to Videos feed (not Shorts)

Every Day at 6AM UTC:
  Fetch YouTube Analytics →
  Update strategy (best templates/times/categories) →
  Commit updated strategy to repo
```

---

## 📊 Content Strategy

### Shorts Format
- **Duration**: ~15 seconds
- **Structure**: Question (3s) → Timer countdown 5→1 (5s) → Answer reveal (1.5s)
- **Templates** (rotated, never repeated consecutively):
  - True / False
  - Multiple Choice
  - Direct Question
  - Guess the Answer
  - Quick Challenge
  - Only Geniuses
  - Memory Test
  - Visual Question

### Long Videos Format
- **Duration**: 5–8 minutes
- **Structure**: Intro → 20 questions (question + timer + answer each) → Outro
- **Published to**: Videos feed (not Shorts)

---

## 🛡️ Anti-Duplicate & Safety Rules

- Questions not repeated within **15 days**
- Titles not repeated within **7 days**
- CTAs not repeated within **3 days**
- Template never same as previous video
- Maximum 4 Shorts per day
- Maximum 4 Long Videos per week
- Minimum 2 hours between Shorts
- Varied posting times (never same time daily)
- Automatic jitter delay before uploads

---

## 🔁 Fallback Chain

| Component | Primary → Fallback chain |
|---|---|
| Question generation | Gemini → Groq → OpenAI → OpenRouter → Internal bank |
| Voice audio | ElevenLabs → CambAI → OpenAI TTS → HuggingFace → gTTS (free) |
| Background images | Pexels → Pixabay → Unsplash → NASA → Gradient |
| YouTube upload | Slot 3 → Slot 1 → Slot 2 |
| Failed runs | Auto-retry via `auto_recovery.yml` |

---

## 📁 Project Structure

```
.github/
  workflows/
    first_run.yml          ← Triggers immediately on first push
    publish_shorts.yml     ← 4x daily (cron)
    publish_long.yml       ← 4x weekly (cron)
    analytics.yml          ← Daily analytics update
    auto_recovery.yml      ← Auto-retry failed jobs

src/
  orchestrator_short.py   ← Short video pipeline
  orchestrator_long.py    ← Long video pipeline
  content/
    generator.py           ← Question generation (AI + internal bank)
  audio/
    tts.py                 ← Text-to-speech (multi-provider)
  video/
    background.py          ← Background image fetcher
    renderer_short.py      ← Short video renderer (FFmpeg)
    renderer_long.py       ← Long video renderer (FFmpeg)
    thumbnail.py           ← Thumbnail generator (Pillow)
  seo/
    engine.py              ← Title/description/tags/hashtags
  publisher/
    youtube.py             ← YouTube API uploader
  analytics/
    manager.py             ← Analytics fetcher & strategy updater
  utils/
    dedup.py               ← Anti-duplicate logic
    rate_limiter.py        ← Rate limiting & safety layer

data/                      ← Persisted via GitHub Actions cache
  published/               ← Upload logs
  analytics/               ← Analytics data & strategy
  dedup/                   ← Dedup fingerprints

assets/
  backgrounds/             ← Downloaded background images
  thumbnails/              ← Generated thumbnails
```

---

## 🔑 Getting YouTube OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable **YouTube Data API v3**
3. Create **OAuth 2.0 credentials** (Desktop app type)
4. Download credentials JSON
5. Use [OAuth Playground](https://developers.google.com/oauthplayground/) or run locally to get refresh token with scope: `https://www.googleapis.com/auth/youtube.upload`

---

## 📈 Monetization Timeline

To reach YouTube Partner Program requirements (1,000 subscribers + 4,000 watch hours):
- **Shorts** generate views quickly via the Shorts feed algorithm
- **Long Videos** accumulate watch hours
- At 4 Shorts/day: ~120 Shorts/month of high-engagement content
- At 4 Long Videos/week: ~16 hours of watch-time content/month

---

*System runs 100% on GitHub — no local machine, no server, no cost beyond API usage.*
