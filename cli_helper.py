#!/usr/bin/env python
"""
CLI Helper script for managing YouTube auto uploads.
"""
import argparse
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone


def run_command(cmd, description=""):
    """Run a shell command and print results."""
    if description:
        print(f"\n🔄 {description}")
    print(f"$ {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"✗ Command failed: {e}")
        return False


def cmd_bootstrap(args):
    """Bootstrap the system with first content."""
    print("🚀 Bootstrapping system...")
    date = args.date or datetime.now(timezone.utc).strftime("%Y%m%d")
    
    # Create directory structure
    Path("state").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)
    Path("out").mkdir(exist_ok=True)
    
    # Run bootstrap
    return run_command(
        ["python", "-m", "yt_auto", "bootstrap", "--date", date],
        "Publishing first short..."
    )


def cmd_publish_shorts(args):
    """Publish all daily shorts."""
    print("📱 Publishing daily shorts...")
    all_success = True
    
    for slot in [1, 2, 3, 4]:
        success = run_command(
            ["python", "-m", "yt_auto", "short", "--slot", str(slot)],
            f"Publishing short slot {slot}..."
        )
        all_success = all_success and success
    
    return all_success


def cmd_publish_long(args):
    """Publish weekly long-form video."""
    print("🎬 Publishing long-form video...")
    date = args.date or datetime.now(timezone.utc).strftime("%Y%m%d")
    
    return run_command(
        ["python", "-m", "yt_auto", "long", "--date", date],
        "Publishing long-form video..."
    )


def cmd_analyze(args):
    """Analyze performance and optimize strategy."""
    print("📊 Analyzing performance...")
    
    return run_command(
        ["python", "-m", "yt_auto", "analyze"],
        "Running analysis..."
    )


def cmd_test(args):
    """Test system components."""
    print("🧪 Testing system...")
    
    return run_command(
        ["python", "test_system.py"],
        "Running system tests..."
    )


def cmd_status(args):
    """Show system status."""
    print("📈 System Status")
    print("=" * 50)
    
    state_file = Path("state/state.json")
    if state_file.exists():
        import json
        with open(state_file) as f:
            state = json.load(f)
        
        publishes = state.get("publishes", {})
        today_key = datetime.now(timezone.utc).strftime("%Y%m%d")
        today_stats = publishes.get(today_key, {})
        
        shorts = today_stats.get("shorts", {})
        long_vid = today_stats.get("long")
        
        print(f"Bootstrapped: {state.get('bootstrapped', False)}")
        print(f"Shorts today: {len(shorts)}/4")
        print(f"Long video today: {'Yes' if long_vid else 'No'}")
        print()
        
        for slot, info in shorts.items():
            vid_id = info.get("video_id", "?")
            print(f"  Slot {slot}: {vid_id}")
    else:
        print("✗ Not bootstrapped yet. Run: python cli_helper.py bootstrap")
    
    print("=" * 50)
    return True


def cmd_show_analysis(args):
    """Show performance analysis."""
    print("📊 Performance Analysis")
    print("=" * 50)
    
    analysis_file = Path("state/analysis.json")
    if analysis_file.exists():
        import json
        with open(analysis_file) as f:
            analysis = json.load(f)
        
        for category, items in analysis.items():
            if isinstance(items, dict):
                print(f"\n{category.replace('_', ' ').title()}")
                sorted_items = sorted(
                    items.items(),
                    key=lambda x: x[1].get("avg_score", 0),
                    reverse=True
                )[:3]
                for name, metrics in sorted_items:
                    avg_score = metrics.get("avg_score", 0)
                    count = metrics.get("count", 0)
                    print(f"  • {name}: {avg_score:.2f} ({count} samples)")
    else:
        print("✗ No analysis data yet. Run: python cli_helper.py analyze")
    
    print("=" * 50)
    return True


def cmd_show_schedule(args):
    """Show publishing schedule."""
    print("📅 Publishing Schedule")
    print("=" * 50)
    
    schedule_file = Path("state/schedule.json")
    if schedule_file.exists():
        import json
        with open(schedule_file) as f:
            schedule = json.load(f)
        
        print(f"Week: {schedule.get('week', '?')}")
        print("\nShorts Schedule:")
        for slot, info in schedule.get("shorts_slots", {}).items():
            time = info.get("time", "?")
            published = info.get("published", False)
            status = "✓" if published else "○"
            print(f"  {status} {slot}: {time}")
        
        long_day = schedule.get("long_video_day", "?")
        long_time = schedule.get("long_video_time", "?")
        print(f"\nLong Video: Day {long_day} at {long_time}")
    else:
        print("✗ No schedule yet. Will be created on first run.")
    
    print("=" * 50)
    return True


def cmd_show_risk(args):
    """Show risk assessment."""
    print("🛡️  Risk Assessment")
    print("=" * 50)
    
    risk_file = Path("state/risk.json")
    if risk_file.exists():
        import json
        with open(risk_file) as f:
            risk = json.load(f)
        
        level = risk.get("risk_level", "unknown")
        print(f"Current Risk Level: {level.upper()}")
        
        strikes = len(risk.get("strikes", []))
        claims = len(risk.get("copyright_claims", []))
        warnings = len(risk.get("warnings", []))
        
        print(f"\nStrikes: {strikes}")
        print(f"Copyright Claims: {claims}")
        print(f"Warnings: {warnings}")
        
        if strikes > 0:
            print("\nRecent Strikes:")
            for strike in risk.get("strikes", [])[-3:]:
                print(f"  • {strike.get('reason', '?')}")
    else:
        print("✗ No risk data yet.")
    
    print("=" * 50)
    return True


def cmd_clean(args):
    """Clean output files."""
    print("🧹 Cleaning...")
    
    import shutil
    out_dir = Path("out")
    if out_dir.exists():
        shutil.rmtree(out_dir)
        print("✓ Cleaned out/")
    
    return True


def main():
    """Main CLI."""
    parser = argparse.ArgumentParser(
        prog="YouTube Auto Manager",
        description="Manage YouTube auto-upload system"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Bootstrap
    p_bootstrap = subparsers.add_parser("bootstrap", help="Bootstrap system")
    p_bootstrap.add_argument("--date", help="Date YYYYMMDD", default="")
    p_bootstrap.set_defaults(func=cmd_bootstrap)
    
    # Publish shorts
    p_shorts = subparsers.add_parser("shorts", help="Publish daily shorts")
    p_shorts.set_defaults(func=cmd_publish_shorts)
    
    # Publish long
    p_long = subparsers.add_parser("long", help="Publish long video")
    p_long.add_argument("--date", help="Date YYYYMMDD", default="")
    p_long.set_defaults(func=cmd_publish_long)
    
    # Analyze
    p_analyze = subparsers.add_parser("analyze", help="Analyze performance")
    p_analyze.set_defaults(func=cmd_analyze)
    
    # Test
    p_test = subparsers.add_parser("test", help="Run tests")
    p_test.set_defaults(func=cmd_test)
    
    # Status
    subparsers.add_parser("status", help="Show status").set_defaults(func=cmd_status)
    
    # Show analysis
    subparsers.add_parser("analysis", help="Show analysis").set_defaults(
        func=cmd_show_analysis
    )
    
    # Show schedule
    subparsers.add_parser("schedule", help="Show schedule").set_defaults(
        func=cmd_show_schedule
    )
    
    # Show risk
    subparsers.add_parser("risk", help="Show risk").set_defaults(func=cmd_show_risk)
    
    # Clean
    subparsers.add_parser("clean", help="Clean output").set_defaults(func=cmd_clean)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 2
    
    try:
        result = args.func(args)
        return 0 if result else 1
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
