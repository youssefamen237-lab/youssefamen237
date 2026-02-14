#!/usr/bin/env python
"""
🎬 SHORTS PUBLISHER - Publishes one short to YouTube
نشر شورتس واحد بالفعل إلى اليوتيوب
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
        "YT_CLIENT_ID_1",
        "YT_CLIENT_SECRET_1",
        "YT_REFRESH_TOKEN_1",
    ]
    
    missing = [e for e in required_env if not os.getenv(e)]
    if missing:
        print(f"❌ ERROR: Missing required YouTube credentials:")
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
    
    # Get current date and slot
    now = datetime.now(timezone.utc)
    date_yyyymmdd = now.strftime("%Y%m%d")
    
    # Calculate which slot (1-4)
    hour = now.hour
    slot = (hour // 6) % 4 + 1  # 0-5=>1, 6-11=>2, 12-17=>3, 18-23=>4
    
    print(f"📅 Publishing short for {date_yyyymmdd} slot {slot}...")
    
    # Run the publish command
    ret = os.system(f"python -m yt_auto short --slot {slot} --date {date_yyyymmdd}")
    
    if ret == 0:
        print(f"✅ Short published successfully!")
        return 0
    else:
        print(f"❌ Failed to publish short")
        return ret

if __name__ == "__main__":
    sys.exit(main())
