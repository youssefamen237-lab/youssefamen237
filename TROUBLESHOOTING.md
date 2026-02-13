# 🔧 Troubleshooting Guide

## Common Issues & Solutions

### 1. YouTube Authentication Errors

#### Error: "YouTube authentication failed"
```
Error: Google auth failed. Invalid token.
```

**Solutions:**
1. ✅ Verify `YT_REFRESH_TOKEN_3` is valid
2. ✅ Check token hasn't expired (> 6 months old = expired)
3. ✅ Get new token:
   ```bash
   python get_youtube_token.py
   ```
4. ✅ Verify `YT_CLIENT_ID_3` and `YT_CLIENT_SECRET_3` match credentials.json
5. ✅ Check YouTube API is enabled in Google Cloud Console

#### Error: "Channel ID not found"
```
Error: Channel not found with ID: UCxxxxxx
```

**Solutions:**
1. ✅ Get correct channel ID from YouTube Studio → Settings
2. ✅ Format: Must start with `UC` (e.g., `UC1234567890`)
3. ✅ Update `YT_CHANNEL_ID` in secrets
4. ✅ Try with `forUsername` instead of channel ID

---

### 2. API Key Issues

#### Error: "Invalid API key"
```
Error: API key is not valid
```

**Solutions:**
1. ✅ Copy-paste key exactly (no spaces)
2. ✅ Verify key hasn't been disabled in provider dashboard
3. ✅ Check key quota hasn't been exceeded
4. ✅ Verify key permissions are correct
5. ✅ Try regenerating key from provider

#### Error: "Quota exceeded"
```
Error: YouTube API quota exceeded
```

**Solutions:**
1. ✅ Check API quota in Google Cloud Console
2. ✅ Wait until quota resets (usually next day)
3. ✅ Reduce upload frequency in config
4. ✅ Get higher quota tier (contact support)

---

### 3. Video Production Errors

#### Error: "FFmpeg not found"
```
Error: ffmpeg not found. Install FFmpeg.
```

**Solutions:**
1. ✅ Install FFmpeg:
   ```bash
   # Ubuntu/Debian
   sudo apt-get install ffmpeg
   
   # macOS
   brew install ffmpeg
   
   # Windows
   choco install ffmpeg
   ```

2. ✅ Verify installation:
   ```bash
   ffmpeg -version
   ffprobe -version
   ```

3. ✅ Add to PATH if needed

#### Error: "Out of memory during video creation"
```
Error: MemoryError: Unable to allocate memory
```

**Solutions:**
1. ✅ Reduce video quality/resolution
2. ✅ Lower FPS setting (30 → 24)
3. ✅ Reduce video length
4. ✅ Close other processes
5. ✅ Increase system RAM
6. ✅ Enable swap space

#### Error: "Video not readable after generation"
```
Error: ffprobe: Invalid video file
```

**Solutions:**
1. ✅ Check video codec (use h264)
2. ✅ Verify audio format (AAC recommended)
3. ✅ Try different output codec
4. ✅ Check available disk space
5. ✅ Run video verification: `ffmpeg -v error -i output.mp4 -f null - 2>&1`

---

### 4. Database Errors

#### Error: "Database disk image is malformed"
```
Error: database disk image is malformed (sqlite3.DatabaseError)
```

**Solutions:**
1. ✅ Rebuild database:
   ```bash
   rm db/system.db
   python -c "from src.database import DatabaseManager; db = DatabaseManager()"
   ```

2. ✅ Restore from backup if available
3. ✅ Check disk space (run `df -h`)
4. ✅ Verify SQLite is installed properly

#### Error: "Database is locked"
```
Error: database is locked (sqlite3.OperationalError)
```

**Solutions:**
1. ✅ Stop other processes accessing database
2. ✅ Close database connections properly
3. ✅ Remove lock files:
   ```bash
   rm db/system.db-journal
   rm db/system.db-wal
   ```
4. ✅ Restart the engine

---

### 5. Content Generation Issues

#### Error: "No questions generated after max attempts"
```
Error: Could not generate unique content
```

**Solutions:**
1. ✅ Check similarity threshold might be too high
2. ✅ Add more question types to database
3. ✅ Clear old content if needed
4. ✅ Adjust content diversity settings

#### Error: "Safety check rejected content multiple times"
```
Warning: Content rejected 5 times, skipping
```

**Solutions:**
1. ✅ Check banned words configuration
2. ✅ Review flagged content in logs
3. ✅ Disable one safety check temporarily:
   - In config: `safe_content_classifier: false`
4. ✅ Manual review of rejected questions

---

### 6. Upload Issues

#### Error: "Upload failed - retrying"
```
Error: Upload failed after 3 attempts
```

**Solutions:**
1. ✅ Check internet connection
2. ✅ Verify YouTube API quota
3. ✅ Check server status: https://status.youtube.com
4. ✅ Try again later (transient error)
5. ✅ Check file permissions on video
6. ✅ Verify video file isn't corrupted

#### Error: "Rate limited by YouTube"
```
Error: 403 Forbidden - rateLimitExceeded
```

**Solutions:**
1. ✅ Reduce upload frequency
2. ✅ Wait longer between uploads
3. ✅ Increase random delays
4. ✅ Use different YouTube account
5. ✅ Check daily quota usage

---

### 7. GitHub Actions Issues

#### Workflow: "Action failed to authenticate"
```
Error: Authentication failed for GitHub
```

**Solutions:**
1. ✅ Verify GitHub Secrets are set correctly
2. ✅ Repo Settings → Secrets → check all keys present
3. ✅ Test secret access in workflow
4. ✅ Recreate secrets if needed

#### Workflow: "Timeout after 8 hours"
```
Error: Job exceeded 8-hour timeout
```

**Solutions:**
1. ✅ Reduce operations per run
2. ✅ Parallelize tasks
3. ✅ Optimize video generation
4. ✅ Use `--single-cycle` mode (default)

#### Workflow: "Cannot push to repository"
```
Error: Permission denied - could not push
```

**Solutions:**
1. ✅ Settings → Actions → Permissions
2. ✅ Enable "Read and write permissions"
3. ✅ Check branch protection rules
4. ✅ Verify no required status checks

---

### 8. Audio/Voice Issues

#### Error: "ElevenLabs API error 401"
```
Error: Invalid API key - Authentication failed
```

**Solutions:**
1. ✅ Verify ELEVEN_API_KEY is correct
2. ✅ Check account hasn't been suspended
3. ✅ Try regenerating API key
4. ✅ Fallback to Google TTS (auto)

#### Error: "Audio file is silent or empty"
```
Warning: Generated audio is shorter than expected
```

**Solutions:**
1. ✅ Check text isn't too short
2. ✅ Verify language setting
3. ✅ Try different voice
4. ✅ Check API response format

#### Error: "Music file won't load"
```
Error: Unable to load music file - unsupported format
```

**Solutions:**
1. ✅ Convert to MP3 or WAV
2. ✅ Check filename doesn't have special chars
3. ✅ Verify file permissions
4. ✅ Try with different audio player

---

### 9. Performance Issues

#### Problem: Engine runs slowly
```
App takes 30+ minutes per upload cycle
```

**Solutions:**
1. ✅ Profile code: `python -m cProfile src/brain.py`
2. ✅ Check database query performance
3. ✅ Optimize video encoding settings
4. ✅ Increase machine resources
5. ✅ Parallelize where possible

#### Problem: High CPU/Memory usage
```
CPU: 100% | Memory: 90%
```

**Solutions:**
1. ✅ Monitor with `htop` or `docker stats`
2. ✅ Reduce video quality
3. ✅ Limit concurrent operations
4. ✅ Increase hardware resources
5. ✅ Enable memory limits (see Dockerfile)

#### Problem: Network timeout errors
```
Error: Request timeout after 30 seconds
```

**Solutions:**
1. ✅ Check internet connection
2. ✅ Increase timeout values in config
3. ✅ Check API server status
4. ✅ Move server closer to API endpoints

---

### 10. Shadow Ban / Algorithm Issues

#### Problem: Videos getting very low impressions
```
Warning: Impressions dropped 60% suddenly
```

**Solutions:**
1. ✅ Check for shadow ban in logs
2. ✅ Review recent videos for policy violations
3. ✅ Pause uploads for 48 hours (automatic)
4. ✅ Diversify content format
5. ✅ Review Community Guidelines

#### Problem: CTA not generating engagement
```
Warning: CTR is dropping below 3%
```

**Solutions:**
1. ✅ Review CTA variations in config
2. ✅ Check hook effectiveness
3. ✅ Test different question types
4. ✅ Improve video hook (first 0.7s)
5. ✅ Analyze top-performing videos

---

### Debug Mode

#### Enable verbose logging:
```bash
# Edit src/brain.py
logging.basicConfig(level=logging.DEBUG)

# Or set environment
export LOG_LEVEL=DEBUG
python src/brain.py --single-cycle
```

#### Check specific modules:
```python
# Test database
python -c "
from src.database import DatabaseManager
db = DatabaseManager()
print('DB OK:', db.get_analytics_summary())
"

# Test YouTube API
python -c "
from src.youtube_api import YouTubeManager
yt = YouTubeManager()
print('YouTube OK:', yt.get_channel_analytics() is not None)
"

# Test content generation
python -c "
from src.content_generator import ContentGenerator
from src.database import DatabaseManager
db = DatabaseManager()
gen = ContentGenerator(db)
q = gen.generate_question()
print('Question OK:', q is not None)
"
```

#### View full logs:
```bash
# Real-time
tail -f logs/brain_*.log

# Last N lines
tail -100 logs/brain_*.log

# Search for errors
grep ERROR logs/brain_*.log

# Show all API calls
grep -E "API|http" logs/brain_*.log
```

---

## Getting Help

1. **Check logs first:**
   ```bash
   ls logs/
   tail -50 logs/brain_*.log
   ```

2. **Search existing issues:**
   - GitHub Issues
   - Discussions

3. **Create detailed bug report:**
   - Include error message
   - Include full log excerpt
   - Include steps to reproduce
   - Include system info (OS, Python version)

4. **Community support:**
   - GitHub Discussions
   - Stack Overflow tag: `youtube-api`

---

**Most issues are resolved by checking logs first!**

*Last Updated: February 2026*
