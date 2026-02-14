from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from yt_auto.cli import main

if __name__ == "__main__":
    # Load .env file if it exists
    env_file = Path(".env")
    if env_file.exists():
        load_dotenv(env_file)
    
