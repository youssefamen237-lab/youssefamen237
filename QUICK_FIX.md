# 🚨 GitHub Actions Workflow Failure - Quick Fix

Your GitHub Actions workflow failed because **API Keys are not configured**.

## ⚡ 3-Minute Fix

### Option 1: Auto Setup (Fastest)
```bash
bash setup-github.sh
# Then choose option 3 (Manual GitHub Secrets)
# and follow the steps
```

### Option 2: Manual Steps

1. **Open GitHub Settings**
   - Go to your repository
   - Settings → Secrets and variables → Actions

2. **Add Required Secrets**
   ```
   YT_CLIENT_ID_3 = (from Google Cloud Console)
   YT_CLIENT_SECRET_3 = (from Google Cloud Console)
   YT_REFRESH_TOKEN_3 = (get from below)
   YT_CHANNEL_ID = (your YouTube channel ID)
   OPENAI_API_KEY = (from OpenAI platform)
   ```

3. **Get YouTube Refresh Token**
   ```bash
   python get-yt-token.py
   ```
   (This will open a browser for OAuth2)

4. **Re-run Workflow**
   - Go to Actions tab
   - Click Smart Shorts Daily Production
   - Click "Run workflow"

---

## 📍 Where to Get Keys?

| Key | Where |
|-----|-------|
| `YT_CLIENT_ID_3` | https://console.cloud.google.com/ |
| `YT_CLIENT_SECRET_3` | Same place |
| `YT_REFRESH_TOKEN_3` | Run `python get-yt-token.py` |
| `YT_CHANNEL_ID` | YouTube Studio → Settings |
| `OPENAI_API_KEY` | https://platform.openai.com |

---

## ✅ Verify Setup

After adding secrets:
```bash
# Run locally to test
source .env && python src/brain.py --single-cycle
```

Or just push to GitHub:
```bash
git add .
git commit -m "Add github action workflow"
git push
```

---

## 🎯 Expected Result After Fix

```
✅ produce-and-upload: Success (2-5 min)
✅ performance-analysis: Success (1 min)
✅ First YouTube Short uploaded!
```

---

## ❓ Still Not Working?

Read these guides in order:
1. [GITHUB_ACTIONS_FIX.md](GITHUB_ACTIONS_FIX.md) - Detailed troubleshooting
2. [SETUP.md](SETUP.md) - Complete setup guide
3. [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - General issues

---

**Status:** Ready to deploy once secrets are added ✅
