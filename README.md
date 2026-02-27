# Quiz Plus — Self-Governing AI YouTube Channel

Fully automated YouTube channel system. 4 Shorts/day + 1 Long Video/week + 2 Community Polls/day.
100% free tools. Zero human intervention after deployment.

---

## Project Structure

```
quiz-plus/
├── .github/
│   └── workflows/
│       ├── first_run.yml           ← Run ONCE to launch channel
│       ├── daily_shorts.yml        ← 4 Shorts every day
│       ├── weekly_long_video.yml   ← 1 Long video every Sunday
│       ├── daily_polls.yml         ← 2 Community polls every day
│       └── weekly_analysis.yml     ← Strategy optimization every Saturday
├── src/
│   ├── content_generator.py        ← AI question + metadata generation
│   ├── tts_engine.py               ← edge-tts + HF Kokoro TTS
│   ├── asset_fetcher.py            ← Backgrounds, SFX, BGM from APIs
│   ├── video_composer.py           ← Short video builder (FFmpeg + Pillow)
│   ├── long_video_composer.py      ← Long video builder
│   ├── youtube_uploader.py         ← YouTube Data API v3 uploader
│   ├── polls_engine.py             ← Community polls poster
│   ├── shorts_runner.py            ← Daily shorts pipeline
│   ├── long_runner.py              ← Weekly long video pipeline
│   └── project_manager.py         ← Analytics + strategy optimizer
├── assets/
│   ├── backgrounds/                ← Cached BG images/videos
│   ├── music/                      ← Cached BGM
│   └── sfx/                        ← Cached SFX (tick, ding, whoosh)
├── data/
│   ├── strategy.json               ← Current optimized strategy
│   ├── videos_log.json             ← All published videos log
│   ├── polls_log.json              ← All published polls log
│   ├── used_questions.json         ← Anti-duplicate question tracker
│   └── analytics_log.json         ← Weekly analytics snapshots
└── requirements.txt
```

---

## Deployment Steps

### 1. Fork / Create GitHub Repository
Create a new private or public GitHub repository.

### 2. Add All GitHub Secrets
Go to: Settings → Secrets and Variables → Actions → New repository secret

Add ALL of these secrets (exact names):
```
GEMINI_API_KEY
GROQ_API_KEY
OPENROUTER_KEY
HF_API_TOKEN
PEXELS_API_KEY
PIXABAY_API_KEY
FREESOUND_API
UNSPLASH_ACCESS_KEY
YT_CLIENT_ID_1
YT_CLIENT_SECRET_1
YT_REFRESH_TOKEN_1
YT_CLIENT_ID_2
YT_CLIENT_SECRET_2
YT_REFRESH_TOKEN_2
YT_CLIENT_ID_3
YT_CLIENT_SECRET_3
YT_REFRESH_TOKEN_3
YT_CHANNEL_ID
YOUTUBE_API_KEY
```

### 3. YouTube OAuth2 Setup
For each credential set (1, 2, 3):
1. Go to Google Cloud Console → Create Project
2. Enable YouTube Data API v3
3. Create OAuth2 credentials (Desktop app)
4. Get refresh token using OAuth2 flow
5. Add to GitHub Secrets

### 4. First Launch
Go to Actions tab → "First Run — Initial Launch" → Run workflow → Type "LAUNCH"

This will immediately produce and upload:
- First YouTube Short
- First Long Video

### 5. Automatic Operation
After first run, all workflows run automatically:
- Daily Shorts: Every day at 09:00 UTC (staggered internally)
- Daily Polls: Every day at 11:00 and 19:00 UTC
- Weekly Long Video: Every Sunday at 15:00 UTC
- Weekly Analysis: Every Saturday at 02:00 UTC

---

## Content Strategy

**Shorts Format:**
- Question display with split-screen (question top, B-roll bottom)
- Circular countdown timer (green → red)
- 5-second countdown with tick SFX
- Answer reveal (1.5-2s) with ding SFX
- Moving watermark "Quiz Plus"
- 8 rotating templates, never repeat within 3 videos
- No question repeated within 15 days

**Long Video Format:**
- "The Hardest 50 Questions of the Week"
- Motivational checkpoint every 10 questions
- Trivia fact after every answer
- Dynamic B-roll changes every ~60 seconds

**Community Polls:**
- 2 polls/day
- Questions recycled from 7-day-old Shorts
- Drives subscriber growth via YouTube algorithm

---

## Safety & Compliance
- No copyrighted music (generated or Pixabay royalty-free)
- Original AI-generated questions
- No misleading metadata
- Rate limiting between uploads
- Audio fingerprint variation per video (±2% pitch/speed)
- Moving watermark proving original content

---

## Free Tools Used
| Tool | Purpose |
|------|---------|
| edge-tts | Primary TTS (Microsoft Neural) |
| HF Kokoro TTS | Fallback TTS |
| Gemini API | Question generation (free tier) |
| Groq API | Question generation fallback (free) |
| OpenRouter | Third AI fallback (free models) |
| Pexels API | Background videos/images |
| Pixabay API | Background videos/music |
| Freesound API | SFX |
| Unsplash API | Background images |
| FFmpeg | Video encoding |
| YouTube Data API v3 | Upload + analytics |
