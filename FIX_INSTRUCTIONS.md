# ⚠️ WORKFLOW FAILED - See QUICK_FIX.md

Your GitHub Actions failed because **API Keys are missing from GitHub Secrets**.

## 🚀 3-Minute Fix

### Quick Start
```bash
bash setup-github.sh
# Choose option 3 (Manual GitHub Secrets)
# Add your 5 API keys
# Re-run workflow
```

### Or Manually
1. Go to: `Settings → Secrets and variables → Actions`
2. Add these 5 secrets:
   - `YT_CLIENT_ID_3`
   - `YT_CLIENT_SECRET_3`
   - `YT_REFRESH_TOKEN_3`
   - `YT_CHANNEL_ID`
   - `OPENAI_API_KEY` (or `GEMINI_API_KEY`)
3. Go to `Actions` tab → `Run workflow`

## 📚 Detailed Guides
- **Quick Fix (3 min):** Read [QUICK_FIX.md](QUICK_FIX.md)
- **Detailed Help:** Read [GITHUB_ACTIONS_FIX.md](GITHUB_ACTIONS_FIX.md)
- **What Was Fixed:** Read [FIXED_EXPLANATION.md](FIXED_EXPLANATION.md)
- **Step by Step (Arabic):** Read [NEXT_STEPS_AR.md](NEXT_STEPS_AR.md)

## ✅ Tools to Help
```bash
make github-setup       # Interactive setup
make get-yt-token       # Get YouTube token
make quick-fix          # Show quick fix
```

## 🎯 Next Steps
1. **Get YouTube Token:** `python get-yt-token.py`
2. **Add GitHub Secrets:** Go to Settings
3. **Run Workflow:** Go to Actions tab
4. **Monitor:** Watch for ✅ Success!

---

**Status:** ✅ Code Ready | ⏳ Waiting for API Keys
**Time to Fix:** ~5 minutes
