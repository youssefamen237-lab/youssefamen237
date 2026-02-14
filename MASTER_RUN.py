#!/usr/bin/env python
"""
🚀 MASTER BOOTSTRAP - Start Everything
سكريبت واحد فقط لتشغيل كل شيء تلقائياً
"""
import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

def setup_environment():
    """إعداد البيئة"""
    print("🔧 إعداد البيئة...")
    
    # Load .env if exists
    env_file = Path(".env")
    if env_file.exists():
        load_dotenv(env_file)
        print("  ✓ Loaded .env configuration")
    
    # Check for YouTube credentials
    required = ["YT_CLIENT_ID_1", "YT_CLIENT_SECRET_1", "YT_REFRESH_TOKEN_1"]
    missing = [e for e in required if not os.getenv(e)]
    if missing:
        print(f"\n⚠️  WARNING: Missing YouTube credentials:")
        for m in missing:
            print(f"   - {m}")
        print("\n➡️  To enable YouTube uploads, add these to .env or GitHub Secrets:")
        print("   Settings → Secrets and variables → Actions")
        print("\nℹ️  System will still generate videos without YouTube credentials.\n")
    
    # تحقق من المجلدات
    for folder in ["state", "data", "out", "assets/backgrounds"]:
        Path(folder).mkdir(parents=True, exist_ok=True)
    
    # تهيئة state.json
    state_path = Path("state/state.json")
    if not state_path.exists():
        default_state = {
            "version": 1,
            "bootstrapped": False,
            "used": [],
            "publishes": {}
        }
        state_path.write_text(json.dumps(default_state, indent=2))
        print(f"✓ تم إنشاء {state_path}")
    
    print("✓ البيئة جاهزة")

def run_bootstrap():
    """تشغيل bootstrap واحد فقط"""
    print("\n🚀 بدء النظام الأول...")
    os.system("python -m yt_auto bootstrap 2>&1")
    print("\n✓ تم بدء النظام")

def setup_automation():
    """تحضير الأتمتة"""
    print("\n⚙️ تحضير الأتمتة...")
    
    # تحقق من GitHub integration
    if os.getenv("GITHUB_TOKEN"):
        print("✓ GitHub Token متوفر")
    else:
        print("⚠️ GitHub Token غير متوفر - GitHub Actions قد لا تعمل")
    
    print("\n✓ الأتمتة جاهزة")

def show_status():
    """عرض الحالة"""
    print("\n📊 حالة النظام:")
    
    state_path = Path("state/state.json")
    if state_path.exists():
        with open(state_path) as f:
            state = json.load(f)
        
        print(f"  • Bootstrapped: {state.get('bootstrapped', False)}")
        print(f"  • Used Questions: {len(state.get('used', []))}")
        print(f"  • Published Days: {len(state.get('publishes', {}))}")
    
    print("\n✨ النظام جاهز!")
    print("\n📌 الخطوات التالية:")
    print("  1. سيتم نشر 4 شورتس يومياً تلقائياً")
    print("  2. سيتم نشر فيديوهات طويلة أسبوعياً")
    print("  3. سيتم التحليل يومياً")
    print("\n🎯 كل شيء أتوماتيك الآن - لا تحتاج لفعل شيء!")

def main():
    """المسار الرئيسي"""
    print("╔════════════════════════════════════════════════════════╗")
    print("║        YouTube Auto Upload - Master Bootstrap         ║")
    print("║                تشغيل النظام بنقرة واحدة                ║")
    print("╚════════════════════════════════════════════════════════╝\n")
    
    try:
        setup_environment()
        run_bootstrap()
        setup_automation()
        show_status()
        print("\n✅ تم التشغيل بنجاح!\n")
        return 0
    except Exception as e:
        print(f"\n❌ خطأ: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
