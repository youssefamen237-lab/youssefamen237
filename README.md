# 🎬 Smart Shorts - YouTube Automation Engine

**A Self-Governing Growth Engine for YouTube Shorts**

Dynamic, intelligent automation system that produces, publishes, and optimizes YouTube Shorts with zero human intervention.

## 🎯 Core Features

### ✅ Fully Autonomous Production
- **100% Automated Content Generation** - Creates quiz/trivia shorts automatically
- **Real YouTube Integration** - Direct API uploads with full YouTube Studio integration  
- **Content Diversity** - 8+ different question types (True/False, Multiple Choice, Math, Brain Teasers, etc.)
- **Zero Repetition** - Semantic similarity checking prevents duplicate content
- **Trend Injection** - Automatically incorporates trending topics

### 📊 Intelligent Analytics
- **Performance Attribution** - Tracks 15+ metrics per video
- **Real-Time Strategy Evolution** - Automatically adjusts based on performance
- **Behavioral Drift** - Changes patterns every 7 days to avoid detection
- **Shadow Ban Detection** - Monitors for algorithm suppression
- **Attention Curve Optimization** - Analyzes viewer retention patterns

### 🔒 Safety & Compliance
- **Content Safety Scanning** - Gemini + OpenAI moderation APIs
- **Strike Prevention** - Blocks banned words and sensitive topics
- **Copyright Protection** - No unlicensed video/music usage
- **Age-Appropriate** - "Made for Kids" flagging

### 📤 Smart Publishing
- **Randomized Upload Times** - ±30 minute variance, no fixed schedule
- **Adaptive Publishing Density** - 4-8 videos/day based on performance
- **Upload Pattern Obfuscation** - Never 4+ videos in 10 minutes
- **Automatic Retries** - Smart grace period retry system
- **Disaster Recovery** - Handles API failures gracefully

### 🎤 Audio & Visuals
- **AI Voiceovers** - ElevenLabs, gTTS with gender variation
- **Music Intelligence** - BPM & mood analysis, 3-use-per-week limit
- **Dynamic Backgrounds** - Gradient generation + smart reuse
- **Video Format** - Optimized 9:16 aspect ratio (1080x1920)

### 📈 Growth Optimization
- **A/B Testing Framework** - Tests CTAs, voices, timers, backgrounds
- **Comment Automation** - Intelligent replies to first 5 comments
- **Playlist Auto-Management** - Automatic organization & reordering
- **Monetization Focus** - Target: >85% retention, >7% CTR, >70% completion
- **Weekly Long-Form** - Compiles top 10 shorts into 4-6 min videos

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- FFmpeg + FFprobe
- GitHub Account with Secrets configured
- YouTube API Access (via OAuth2)
- API Keys (listed below)

### Installation

```bash
# Clone repository
git clone https://github.com/youssefamen237/youssefamen237.git
cd youssefamen237

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your API keys
```

### GitHub Secrets Configuration

**YouTube (Required)**
```
YT_CLIENT_ID_3
YT_CLIENT_SECRET_3
YT_REFRESH_TOKEN_3
YT_CHANNEL_ID
YOUTUBE_API_KEY
```

**AI/LLM APIs (At least 1)**
```
OPENAI_API_KEY or GEMINI_API_KEY or GROQ_API_KEY
```

**Audio/Voice (Optional)**
```
ELEVEN_API_KEY
ASSEMBLYAI
```

**Asset APIs (Recommended)**
```
PEXELS_API_KEY
PIXABAY_API_KEY
UNSPLASH_ACCESS_KEY
UNSPLASH_ID
UNSPLASH_SECRET_KEY
```

**Trends/News (Optional)**
```
SERPAPI
NEWS_API
TAVILY_API_KEY
```

**See `.env.example` for complete list of 47 API keys**

### Running

#### Single Production Cycle (GitHub Actions)
```bash
python src/brain.py --single-cycle
```

#### Analysis Only
```bash
python src/brain.py --analyse-only
```

#### Full Scheduler (Local Development)
```bash
python src/brain.py --schedule
```

## 📁 Project Structure

```
youssefamen237/
├── src/
│   ├── brain.py                 # Main orchestration engine
│   ├── database.py              # SQLite database manager
│   ├── youtube_api.py           # YouTube API wrapper
│   ├── content_generator.py     # Question/content generation
│   ├── video_engine.py          # Video production (FFmpeg)
│   ├── upload_scheduler.py      # Upload timing & analytics
│   ├── content_safety.py        # Safety checking & optimizations
│   ├── analytics.py             # Performance analysis
│   └── report_generator.py      # Report generation
├── assets/
│   ├── backgrounds/             # PNG/MP4 background images
│   ├── music/                   # MP3/WAV audio files
│   └── fonts/                   # TTF/OTF font files
├── db/
│   └── system.db                # SQLite database
├── logs/                        # Log files & reports
├── cache/                       # Temporary cache
├── config/                      # Configuration files
├── .github/workflows/
│   └── smart_shorts.yml         # GitHub Actions workflow
├── requirements.txt             # Python dependencies
├── README.md                    # This file
└── .env.example                # Environment variables template
```

## 📊 Data Architecture

### Content DNA Tracking
Every video's unique characteristics are hashed:
- Question text hash
- Audio signature hash
- Background image hash
- Music file hash
- Element arrangement hash

**Similarity Threshold:** >70% hash similarity = regenerate content

### Performance Attribution
Each video tracked with 15+ metrics:
- Watch time, Completion rate, CTR, Comments, Rewatch
- Voice gender, Question type, Video length
- Upload time, CTA used, Music BPM

**Performance Score Formula:**
```
Score = (WatchTime × 0.35) + (Completion × 0.25) + 
        (CTR × 0.15) + (Comments × 0.1) + (Rewatch × 0.15)
```

### Strategy Evolution
System automatically adjusts based on 7-day rolling averages:
- Question type preferences (CTR < 3% = reduce, > 8% = increase)
- Voice gender ratios (weighted, not absolute)
- Upload density (±20% based on performance)
- CTA variations
- Timer durations

## 🔧 Configuration

### Database Schema
- `content_dna` - Unique content fingerprints
- `video_performance` - Detailed metrics per video
- `upload_history` - Upload attempts & results
- `strategy_evolution` - Historical strategy changes
- `music_metadata` - Audio file tracking
- `background_tracking` - Background image usage
- `ab_tests` - A/B test results
- `comment_automation` - Reply log
- `playlist_management` - Video organizing
- Plus 3 more specialized tables

### Upload Limits
- **Daily:** 4-8 videos (adaptive based on performance)
- **Weekly:** Max 50 videos
- **API Failures:** Max 2 per minute

### Behavioral Randomization
- Upload time variance: ±30 minutes
- Delay before upload: 2-11 minutes random
- Speech speed variation: ±2%
- Video length variation: ±1.2 seconds
- 7-day behavioral drift: Question type, CTAs, music

## 📈 Performance Targets

🎯 **Target Metrics**
- Retention: >85%
- CTR: >7%
- Completion: >70%

### Shadow Ban Detection
Automatic pause if:
- Impressions drop 60%+ suddenly
- CTR stable but impressions tanked
- Monitors via analytics every 12 hours

### Adaptive Density
- Excellent performance (72h): +20% upload speed
- Poor performance: -30% upload speed
- Sudden drop: Stop 24 hours
- Shadow ban suspect: Stop 48 hours

## 🔐 Security

- **No Hardcoded Keys** - All secrets from GitHub/Environment
- **Rate Limiting** - Respects YouTube API quotas
- **Error Handling** - Graceful degradation on API failures
- **Audit Logging** - All actions logged with timestamp
- **Content Filtering** - 20+ banned words list

## 📝 Logging

Logs stored in `/logs/` directory:
- `brain_YYYYMMDD.log` - Main engine logs
- `analytics.json` - JSON analytics export
- `production.log` - GitHub Actions output
- `daily_report_YYYYMMDD.json` - Daily metrics
- `weekly_report_YYYY_WNN.json` - Weekly summary
- `financial_report_YYYYMM.json` - Revenue estimates

## 🤖 GitHub Actions Automation

**Workflow:** `smart_shorts.yml`
- Runs 4 times daily at different times
- Single production cycle per run
- Auto-commits database updates
- Discord notifications on failure
- Max 8-hour timeout per run

**Schedule:**
```
08:00 UTC (8 AM)
12:30 UTC (12:30 PM)
17:00 UTC (5 PM)
21:30 UTC (9:30 PM)
```

Each run executes:
1. Content generation & safety check
2. Video production
3. Upload to YouTube
4. Database updates
5. Performance analysis
6. Report generation

## 🎨 Content Types

Supported question formats:
1. **True/False** - Knowledge questions
2. **Multiple Choice** - 4-option selection
3. **Visual Difference** - Spot the difference
4. **Quick Solve** - Math problems
5. **Guess the Answer** - Fill-in-the-blank
6. **Only Geniuses Can Solve** - Hard challenges
7. **5 Second Challenge** - Speed tests
8. **Memory Test** - Sequence/pattern recall
9. **Trivia** - Fact-based knowledge
10. **Brain Teaser** - Logic puzzles
11. **Optical Illusion** - Visual perception
12. **Quick Math** - Arithmetic
13. **Pop Culture** - Entertainment knowledge

## 🔄 Workflow Overview

```
[Daily Trigger]
    ↓
[Analytics Check] → Performance Analysis → Strategy Update
    ↓
[Decision Engine] → Should Upload? → Rate Limit Check
    ↓
[Content Generation] → Safety Check → Regenerate if needed
    ↓
[Audio Generation] → Background Selection → Music Pairing
    ↓
[Video Creation] → Quality Verification → Metadata Hashing
    ↓
[Upload to YouTube] → Retry on Failure → Database Update
    ↓
[Comment Automation] → Monitor Performance → Adjust Strategy
```

## 📚 API Key Requirements (47 Total)

**Essential (At least these):**
- YouTube (3 sets): Client ID, Secret, Refresh Token
- LLM API (choose 1+): OpenAI, Gemini, or Groq
- Optional: Others enhance functionality

**All Available APIs:** See `.env.example` file

## 🚨 Troubleshooting

**Issue: Videos not uploading**
- Check YouTube API credentials
- Verify channel ID is correct
- Check rate limits in logs

**Issue: Low performance scores**
- Review recent video analytics
- Check content safety isn't filtering
- Inspect hook and CTA effectiveness

**Issue: High API failures**
- Space out uploads more
- Check API key quotas
- Verify internet connection

**Issue: Database errors**
- Clear cache folder
- Rebuild database: `rm db/system.db`
- Check disk space

## 📞 Support

- **Issues:** GitHub Issues
- **Discussions:** GitHub Discussions
- **Documentation:** See `/logs/` for detailed reports

## 📄 License

MIT License - See LICENSE file

## ⚠️ Disclaimer

- Comply with YouTube ToS and community guidelines
- Monitor channel health regularly
- Don't rely entirely on automation
- Review content before escalation
- Maintain backup of database

---

**Made with ❤️ for creators** | *Last Updated: February 2026*
