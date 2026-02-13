#!/usr/bin/env python3
import sys

critical = ['requests', 'google.auth', 'googleapiclient', 'moviepy', 'cv2', 'openai', 'groq', 'elevenlabs', 'schedule']
failed = []

for pkg in critical:
    try:
        __import__(pkg.replace('-', '_'))
        print(f'✅ {pkg}')
    except ImportError as e:
        print(f'❌ {pkg}: {e}')
        failed.append(pkg)

if failed:
    print(f'\n⚠️ Failed to import: {failed}')
    sys.exit(1)

print('\n✅ All critical packages OK!')
