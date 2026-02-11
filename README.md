فيما يلي نسخة مصححة ومحسّنة من README.md مع ضبط التنسيق، توحيد المصطلحات، إزالة الغموض، وتحسين قابلية التنفيذ دون تغيير منطق النظام.

Self-Governing AI YouTube Shorts Growth System
Overview

Automated, self-optimizing YouTube Shorts publishing system with:

AI-generated content (Gemini / Groq)

Semantic DNA tracking to prevent duplication

Automated vertical video rendering (1080×1920)

Human-behavior simulation layer

Weekly strategic self-adjustment

Multi-layer content safety filtering

System is designed for autonomous operation after initial configuration.

Initial Setup
1) Fork the Repository

Fork this repository to your GitHub account.

2) Configure GitHub Secrets

Go to:

Settings → Secrets and Variables → Actions

Add the following secrets:

All required API keys (as specified in the project documentation)

YT_CHANNEL_ID — Your YouTube Channel ID

YT_REFRESH_TOKEN — YouTube OAuth refresh token (see OAuth setup section)

3) Initialize Required Folders

Run:

mkdir -p assets/backgrounds
mkdir -p assets/music
mkdir -p assets/fonts
mkdir -p assets/overlays
mkdir -p data/analytics
mkdir -p data/content_memory

4) Add Background Music

Place royalty-free .mp3 files inside:

assets/music/


Recommended: 10–15 tracks

Each track is automatically rotated

Max usage: 3 times per week per track

⚠ Ensure you have full commercial rights to all audio assets.

5) Enable GitHub Workflows

Open the Actions tab.

Enable workflows if prompted.

Verify scheduled workflows are active.

System will begin operating based on configured triggers (cron or event-based).

How It Works
Content Generation

AI generates unique brain teaser content using Gemini or Groq.

Prompts are dynamically adapted based on performance feedback.

DNA Tracking

Semantic hashing prevents content duplication.

Stored in:

data/content_memory/

Video Assembly

MoviePy renders 1080×1920 vertical videos.

Automatic:

Text overlays

Background selection

Music rotation

Timing optimization

Human Simulation Layer

Randomized publishing delays

Slight speed variations

Behavioral drift modeling

Pattern entropy injection

Designed to reduce automation detectability.

Self-Evolution Engine

Weekly analytics analysis

Strategy weight rebalancing

Hook pattern optimization

Retention-based prompt tuning

Strategy state stored in:

data/strategy_state.json

Monitoring

To inspect system behavior:

data/strategy_state.json


Contains:

Performance metrics

Strategy weights

Evolution logs

Publishing velocity

Analytics stored in:

data/analytics/

Critical Implementation Notes
1) YouTube API Quotas

Respects 10,000 units/day limit

Batches analytics requests

Uses efficient endpoint calls

Avoids unnecessary polling

Monitor quota usage via Google Cloud Console.

2) Storage Constraints

GitHub Actions provides ~14GB SSD

Videos are temporary

Rendered assets are not committed to repository

Clean-up runs automatically after publishing

3) OAuth Setup (Manual Step Required)

You must:

Create Google Cloud project

Enable YouTube Data API v3

Create OAuth credentials

Run local OAuth flow

Extract refresh token

Add YT_REFRESH_TOKEN to GitHub Secrets

The system cannot generate this token automatically.

4) Music Compliance

Use royalty-free or licensed tracks only

No copyrighted commercial music

Avoid Content ID matches

Failure to comply may result in:

Monetization loss

Video removal

Channel strikes

5) Safety Layer

Content is filtered through:

Keyword blacklist

Topic compliance check

Strike-risk classifier

Review:

src/safety_checker.py


Adjust blacklist carefully if changing niche.

Operational Notes

Designed for long-term autonomous scaling

Optimized for YouTube Shorts vertical algorithm

Strategy adapts weekly

Publishing begins immediately once workflows are enabled
