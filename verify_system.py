#!/usr/bin/env python3
"""
System Verification Script
Checks if all components are properly configured and working
"""

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, '/workspaces/youssefamen237/src')

print("🔍 System Verification")
print("=" * 60)

checks_passed = 0
checks_failed = 0

# Check 1: Project structure
print("\n1. Project Structure...")
required_dirs = [
    'src', 'db', 'logs', 'cache',
    'assets/backgrounds', 'assets/music', 'assets/fonts',
    'config', '.github/workflows'
]

for dir_path in required_dirs:
    if os.path.isdir(dir_path):
        print(f"   ✅ {dir_path}")
        checks_passed += 1
    else:
        print(f"   ❌ {dir_path} - MISSING")
        checks_failed += 1

# Check 2: Configuration files
print("\n2. Configuration Files...")
required_files = {
    'config/system.json': 'System config',
    '.env.example': 'Environment template',
    'requirements.txt': 'Python dependencies',
    'README.md': 'Documentation',
    'SETUP.md': 'Setup guide',
    '.github/workflows/smart_shorts.yml': 'GitHub Actions workflow'
}

for file_path, desc in required_files.items():
    if os.path.isfile(file_path):
        print(f"   ✅ {desc}")
        checks_passed += 1
    else:
        print(f"   ❌ {desc} - MISSING")
        checks_failed += 1

# Check 3: Python modules
print("\n3. Python Modules...")
required_modules = {
    'src/__init__.py': 'Package init',
    'src/brain.py': 'Main engine',
    'src/database.py': 'Database manager',
    'src/youtube_api.py': 'YouTube API',
    'src/content_generator.py': 'Content generation',
    'src/video_engine.py': 'Video production',
    'src/upload_scheduler.py': 'Scheduler', 
    'src/content_safety.py': 'Safety checking',
    'src/analytics.py': 'Analytics',
    'src/report_generator.py': 'Reporting'
}

for file_path, desc in required_modules.items():
    if os.path.isfile(file_path):
        size = os.path.getsize(file_path)
        if size > 500:  # At least 500 bytes
            print(f"   ✅ {desc} ({size} bytes)")
            checks_passed += 1
        else:
            print(f"   ⚠️  {desc} - TOO SMALL")
            checks_failed += 1
    else:
        print(f"   ❌ {desc} - MISSING")
        checks_failed += 1

# Check 4: Configuration content
print("\n4. Configuration Content...")
try:
    with open('config/system.json', 'r') as f:
        config = json.load(f)
    
    required_keys = ['system', 'production', 'content', 'analytics']
    for key in required_keys:
        if key in config:
            print(f"   ✅ Config has '{key}'")
            checks_passed += 1
        else:
            print(f"   ❌ Config missing '{key}'")
            checks_failed += 1
except Exception as e:
    print(f"   ❌ Config error: {e}")
    checks_failed += 1

# Check 5: Python dependencies
print("\n5. Python Compilation Check...")
try:
    import py_compile
    
    py_files = [
        'src/__init__.py',
        'src/brain.py',
        'src/database.py',
        'src/youtube_api.py',
        'src/content_generator.py',
        'src/video_engine.py',
        'src/upload_scheduler.py',
        'src/content_safety.py', 
        'src/analytics.py',
        'src/report_generator.py'
    ]
    
    all_ok = True
    for py_file in py_files:
        try:
            py_compile.compile(py_file, doraise=True)
        except Exception as e:
            print(f"   ❌ {py_file}: {e}")
            all_ok = False
    
    if all_ok:
        print(f"   ✅ All {len(py_files)} modules compile successfully")
        checks_passed += 1
    else:
        checks_failed += 1

except ImportError:
    print("   ⚠️  py_compile not available")

# Check 6: Import critical modules
print("\n6. Module Import Test...")
try:
    from src.database import DatabaseManager
    print("   ✅ DatabaseManager imports")
    checks_passed += 1
except ImportError as e:
    print(f"   ❌ DatabaseManager import failed: {e}")
    checks_failed += 1

try:
    from src.content_generator import ContentGenerator
    print("   ✅ ContentGenerator imports")
    checks_passed += 1
except ImportError as e:
    print(f"   ❌ ContentGenerator import failed: {e}")
    checks_failed += 1

# Check 7: Environment
print("\n7. Environment Variables...")
env_vars = [
    'YT_CLIENT_ID_3',
    'YT_CLIENT_SECRET_3',
    'YT_REFRESH_TOKEN_3',
    'YT_CHANNEL_ID'
]

env_check_passed = True
for var in env_vars:
    if var in os.environ:
        print(f"   ✅ {var} is set")
        checks_passed += 1
    else:
        print(f"   ℹ️  {var} not set (add to .env or GitHub Secrets)")
        env_check_passed = False

if not env_check_passed:
    print("\n   Note: This is expected if running locally without .env")

# Summary
print("\n" + "=" * 60)
print("📊 VERIFICATION SUMMARY")
print("=" * 60)

total_checks = checks_passed + checks_failed
success_rate = (checks_passed / total_checks * 100) if total_checks > 0 else 0

print(f"✅ Passed: {checks_passed}/{total_checks}")
print(f"❌ Failed: {checks_failed}/{total_checks}")
print(f"📈 Success Rate: {success_rate:.1f}%")

if checks_failed == 0:
    print("\n✅ System verification PASSED!")
    print("🚀 Ready for production deployment")
    sys.exit(0)
else:
    print(f"\n⚠️  {checks_failed} checks failed")
    print("Please resolve issues before deployment")
    sys.exit(1)
