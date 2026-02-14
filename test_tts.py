#!/usr/bin/env python
"""Test TTS with espeak"""
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(".env"))

# Test
from yt_auto.tts import synthesize_tts
from yt_auto.config import load_config

print("🔧 Testing TTS with espeak...")
cfg = load_config()
print(f"  TTS Order: {cfg.tts_order}")

try:
    synthesize_tts(cfg, "Hello world test", Path("/tmp/test_audio.wav"))
    print("✅ Success! TTS is working with espeak")
    
    # Check file
    if Path("/tmp/test_audio.wav").exists():
        size = Path("/tmp/test_audio.wav").stat().st_size
        print(f"  Created: {size} bytes")
except Exception as e:
    print(f"❌ Error: {e}")
