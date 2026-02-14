#!/usr/bin/env python
"""
🤖 DAILY AUTO RUN - Runs automatically every day
يشتغل تلقائياً كل يوم عبر GitHub Actions
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

def main():
    """Main entry point"""
    # Load .env if exists
    env_file = Path(".env")
    if env_file.exists():
        load_dotenv(env_file)
    
        os.system("python -m yt_auto bootstrap 2>&1")
    else:
        print("✓ Already bootstrapped, continuing...")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
