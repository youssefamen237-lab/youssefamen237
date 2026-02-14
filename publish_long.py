#!/usr/bin/env python
"""
📹 LONG PUBLISHER - Publishes one long-form video to YouTube
نشر فيديو طويل بالفعل إلى اليوتيوب
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

def main():
    # Load environment
    load_dotenv(Path(".env"))
    
    # Validate YouTube credentials
    required_env = [
        "YT_CLIENT_ID_2",
        "YT_CLIENT_SECRET_2",
        "YT_REFRESH_TOKEN_2",
        "GITHUB_TOKEN",
    ]
    
    missing = [e for e in required_env if not os.getenv(e)]
    if missing:
        print(f"❌ ERROR: Missing required credentials:")
        for m in missing:
            print(f"   - {m}")
        print("\nAdd these to GitHub Secrets: Settings → Secrets and variables → Actions")
        return 1
    
    # Setup
    Path("out").mkdir(exist_ok=True)
    Path("state").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)
    
    # Run bootstraps first if needed
    state_file = Path("state/state.json")
    if not state_file.exists():
        print("🚀 First run detected - bootstrapping...")
        ret = os.system("python -m yt_auto bootstrap")
        if ret != 0:
            print("❌ Bootstrap failed")
            return ret
    
    # Get current date
    now = datetime.now(timezone.utc)
    date_yyyymmdd = now.strftime("%Y%m%d")
    
    print(f"📅 Publishing long-form video for {date_yyyymmdd}...")
    
    # Run the publish command
    ret = os.system(f"python -m yt_auto long --date {date_yyyymmdd}")
    
    if ret == 0:
        print(f"✅ Long-form video published successfully!")
        return 0
    else:
        print(f"❌ Failed to publish long-form video")
        return ret

if __name__ == "__main__":
    sys.exit(main())
