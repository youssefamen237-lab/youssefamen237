# Self-Governing AI YouTube Shorts Growth System

## Setup

1. **Fork this repository**

2. **Add GitHub Secrets** (Settings &gt; Secrets and Variables &gt; Actions):
   - All API keys listed in the specification
   - `YT_CHANNEL_ID`: Your YouTube channel ID

3. **Initialize folders**:
   ```bash
   mkdir -p assets/{backgrounds,music,fonts,overlays}
   mkdir -p data/{analytics,content_memory}
Add background music:
Place royalty-free MP3s in assets/music/
System will rotate through them (max 3x per week each)
Enable Workflows:
Go to Actions tab
Enable workflows
How it works
Content Generation: AI generates unique brain teasers using Gemini/Groq
DNA Tracking: Prevents duplicate content via semantic hashing
Video Assembly: MoviePy generates 1080x1920 vertical videos
Human Simulation: Random delays, speed variations, behavioral drift
Self-Evolution: Weekly analysis adjusts strategy weights automatically
Safety: Multi-layer content filtering prevents strikes
Monitoring
Check data/strategy_state.json for current system configuration and performance metrics.

---

## Critical Implementation Notes

1. **YouTube Quotas**: The system respects the 10,000 unit/day limit by batching analytics collection and using efficient API calls.

2. **Storage**: GitHub Actions have 14GB SSD storage. Videos are temporary and not committed.

3. **OAuth Setup**: You must manually obtain the YouTube refresh token initially using the OAuth flow locally, then add it to secrets.

4. **Music**: Add 10-15 royalty-free tracks to `assets/music/` manually to avoid copyright issues.

5. **Safety**: The keyword blacklist is conservative. Review `src/safety_checker.py` for your niche.

This system is **production-ready** and will begin publishing immediately upon activation.
