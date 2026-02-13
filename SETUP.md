# 🚀 Complete Setup Guide

## Step 1: YouTube API Setup

### 1.1 Create Google Cloud Project
1. Go to https://console.cloud.google.com
2. Click "Create Project"
3. Name it "Smart Shorts"
4. Wait for creation

### 1.2 Enable YouTube API
1. Search "YouTube Data API"
2. Click "Enable"
3. Go to "Credentials"
4. Click "Create Credentials" → "OAuth 2.0 Client IDs"
5. Choose "Desktop application"
6. Download JSON file

### 1.3 Get Refresh Token
1. Install OAuth helper:
   ```bash
   pip install google-auth-oauthlib
   ```

2. Create script `get_youtube_token.py`:
   ```python
   from google_auth_oauthlib.flow import InstalledAppFlow
   
   SCOPES = ['https://www.googleapis.com/auth/youtube']
   
   flow = InstalledAppFlow.from_client_secrets_file(
       'client_secret.json', SCOPES)
   creds = flow.run_local_server()
   
   print("REFRESH TOKEN:", creds.refresh_token)
   print("CLIENT ID:", creds.client_id)
   print("CLIENT SECRET:", creds.client_secret)
   ```

3. Run and authorize:
   ```bash
   python get_youtube_token.py
   ```

4. Get your **YT_CHANNEL_ID** from YouTube Studio settings

### 1.4 Get YouTube API Key
1. In Google Cloud Console → Credentials
2. Click "Create Credentials" → "API Key"
3. This is your YOUTUBE_API_KEY

## Step 2: AI/LLM API Keys

Choose at least ONE (all recommended):

### OpenAI (Recommended)
- Sign up: https://platform.openai.com
- Create API key in Dashboard
- Get OPENAI_API_KEY

### Google Gemini
- Sign up: https://makersuite.google.com
- Get GEMINI_API_KEY

### Groq (Fast & Free)
- Sign up: https://console.groq.com
- Get GROQ_API_KEY

## Step 3: Voice/Audio APIs

### ElevenLabs (Premium voiceovers)
- Sign up: https://elevenlabs.io
- Get ELEVEN_API_KEY
- Recommended for best quality

### AssemblyAI (Alternative)
- Sign up: https://www.assemblyai.com
- Get ASSEMBLYAI key

## Step 4: Image/Background APIs

### Unsplash (Recommended - free)
- https://unsplash.com/oauth/applications
- Get: UNSPLASH_ACCESS_KEY, UNSPLASH_ID, UNSPLASH_SECRET_KEY
- Highest quality free backgrounds

### Pexels
- https://www.pexels.com/api/
- Get: PEXELS_API_KEY

### Pixabay
- https://pixabay.com/api/
- Get: PIXABAY_API_KEY

### Freepik
- https://www.freepik.com/settings/developers
- Get: FREEPIK_API_KEY

## Step 5: Trends/News APIs

### SerpAPI (Google Trends)
- https://serpapi.com
- Get: SERPAPI
- Essential for trend injection

### NewsAPI
- https://newsapi.org
- Get: NEWS_API

### Tavily (Web search)
- https://tavily.com
- Get: TAVILY_API_KEY

## Step 6: GitHub Setup

### 6.1 Repository Secrets
1. Go to repo Settings → Secrets and Variables → Actions
2. Add each API key as a secret:

```
YT_CLIENT_ID_3
YT_CLIENT_SECRET_3
YT_REFRESH_TOKEN_3
YT_CHANNEL_ID
YOUTUBE_API_KEY
OPENAI_API_KEY
GEMINI_API_KEY
(... all others from .env.example)
```

### 6.2 Enable Actions
1. Go to Actions tab
2. Enable GitHub Actions
3. Allow workflows to write to repo

### 6.3 Configure Budget
1. Settings → Billing → Action usage limits
2. Set monthly usage limits

## Step 7: Local Development (Optional)

### 7.1 Setup Python Environment
```bash
# Create virtual environment
python -m venv venv

# Activate
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt
```

### 7.2 Install System Dependencies
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg ffprobe imagemagick

# macOS
brew install ffmpeg imagemagick

# Windows (with Chocolatey)
choco install ffmpeg imagemagick
```

### 7.3 Create .env File
```bash
cp .env.example .env
# Edit .env with your API keys
```

### 7.4 Test Locally
```bash
# Single production cycle
python src/brain.py --single-cycle

# Analysis only
python src/brain.py --analyse-only
```

## Step 8: Add Assets (Optional)

### Backgrounds
1. Add PNG/MP4 files to `assets/backgrounds/`
2. Recommended: 1080x1920 resolution
3. 2-5 MB per file

### Music
1. Add MP3/WAV files to `assets/music/`
2. Royalty-free only!
3. 60-130 BPM recommended
4. 10-20 seconds duration

### Fonts
1. Add TTF/OTF files to `assets/fonts/`
2. Optional: system fonts used by default

## Step 9: Verify Configuration

### Check Database
```bash
python -c "
from src.database import DatabaseManager
db = DatabaseManager()
summary = db.get_analytics_summary()
print('Database initialized:', summary)
"
```

### Check APIs
```bash
python -c "
from src.youtube_api import YouTubeManager
youtube = YouTubeManager()
print('YouTube connected:', youtube.youtube is not None)
"
```

### Test Content Generation
```bash
python -c "
from src.database import DatabaseManager
from src.content_generator import ContentGenerator
db = DatabaseManager()
gen = ContentGenerator(db)
question = gen.generate_question()
print('Question generated:', question['question'] if question else 'Failed')
"
```

## Step 10: First Run

### GitHub Actions (Recommended)
1. Wait for scheduled run (or manually trigger)
2. Check Actions tab for logs
3. Monitor YouTube channel

### Local Test
```bash
python src/brain.py --single-cycle
```

Monitor the process:
- Check `logs/brain_*.log` for details
- Verify video uploaded to channel
- Check database: `ls -la db/system.db`

## Troubleshooting

### Error: "YouTube authentication failed"
- ✅ Check YT_REFRESH_TOKEN_3 is valid
- ✅ Verify token hasn't expired (older than 6 months)
- ✅ Get new token using get_youtube_token.py script

### Error: "API key not valid"
- ✅ Copy-paste exactly from provider
- ✅ No extra spaces
- ✅ Check key hasn't expired
- ✅ Verify permissions

### Error: "FFmpeg not found"
- ✅ Install FFmpeg (see Step 7.2)
- ✅ Add to PATH
- ✅ Verify: `ffmpeg -version`

### Videos not uploading in CI/CD
- ✅ Check GitHub Secrets are set
- ✅ Verify rate limits
- ✅ Check Actions secrets are accessible
- ✅ Review workflow logs

### Database locked errors
- ✅ Stop other processes accessing db
- ✅ Delete `db/system.db` to rebuild
- ✅ Check disk space

## Advanced Configuration

### Custom Configuration
Edit `config/system.json`:
- Production targets (daily uploads)
- Content parameters
- Algorithm settings
- Performance targets

### Performance Tuning
Edit top of `brain.py`:
- Adjust log level
- Change analyzer intervals
- Modify sleep durations

### Add Custom Content
Extend `content_generator.py`:
- Add question_types
- Add cta_variations
- Add hooks
- Add trivia_questions

## Security Best Practices

1. **Never commit .env file**
   - Add to .gitignore
   - Use GitHub Secrets instead

2. **Rotate API keys monthly**
   - Get new tokens
   - Update Secrets
   - Delete old keys from providers

3. **Monitor rate limits**
   - Check logs for API failures
   - Adjust upload frequency
   - Set billing alerts

4. **Restrict channel access**
   - Use separate Google account
   - Enable 2FA
   - Review connected apps

5. **Backup database**
   - Regularly download db/system.db
   - Keep versioned backups
   - Test restoration

## Success Checklist

- [ ] YouTube API credentials working
- [ ] At least one AI API configured
- [ ] Audio generation API working (optional)
- [ ] GitHub Secrets configured
- [ ] First test cycle completed successfully
- [ ] Video uploaded to channel
- [ ] Logs show no critical errors
- [ ] Database created and populated
- [ ] GitHub Actions workflow enabled
- [ ] Discord webhook configured (optional)

## Next Steps

1. Monitor first 24 hours closely
2. Review generated content quality
3. Adjust parameters if needed
4. Add custom backgrounds/music if desired
5. Enable more advanced features gradually
6. Scale up upload frequency gradually

## Support

- **Questions:** GitHub Issues
- **Bugs:** GitHub Issues with logs
- **Feature Requests:** GitHub Discussions
- **Community Help:** GitHub Discussions

---

**Setup Complete!** Your Smart Shorts engine is ready to run. 🎉
