# Self-Governing AI YouTube Channel System

This is a complete automated system that generates and publishes YouTube content without human intervention.

## Features

- **Automatic Content Generation**: Uses AI models (Gemini, Groq) to generate unique questions and answers
- **Daily Publishing**: Automatically publishes 4 YouTube Shorts daily
- **Weekly Long Videos**: Creates 4 long-form videos per week
- **Smart Scheduling**: Varies posting times to avoid bot detection
- **Content Diversity**: Multiple question templates to prevent repetition
- **Full Automation**: Runs via GitHub Actions on a daily schedule

## Requirements

- Python 3.8+
- Various API keys (see Environment Variables section)

## Setup

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Set up environment variables in `.env` file
4. Add background images to `ai_youtube_channel/images/backgrounds/`
5. Configure GitHub Actions secrets

## Environment Variables

You need to set these in your GitHub repository secrets:

- `GEMINI_API_KEY`: Google Gemini API key
- `GROQ_API_KEY`: Groq API key
- `ELEVEN_API_KEY`: ElevenLabs API key
- `YOUTUBE_API_KEY`: YouTube Data API v3 key
- `YT_CHANNEL_ID`: Target YouTube channel ID
- `YT_CLIENT_ID_1`, `YT_CLIENT_SECRET_1`, `YT_REFRESH_TOKEN_1`: YouTube OAuth credentials
- `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `UNSPLASH_ACCESS_KEY`: Image API keys

## File Structure
