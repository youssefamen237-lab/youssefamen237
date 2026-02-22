"""
Master Runner — the single entry point called by the Auto Publisher workflow.
Runs every hour. Decides intelligently what to do:
  - Publish Short? (if optimal time + daily limit not reached)
  - Publish Long Video? (if right day + time + weekly limit not reached)
  - Update Analytics? (if 6AM UTC — daily analytics refresh)
  - Do nothing? (if no optimal slot active)

This is the brain of the entire autonomous system.
"""

import os
import sys
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Ensure src is in path
sys.path.insert(0, str(Path(__file__).parent))

from utils.scheduler import (
    should_publish_short_now,
    should_publish_long_now,
    get_schedule_summary,
    log_scheduled_publish,
)


def run_analytics():
    """Update analytics and strategy"""
    try:
        print("\n[Master] 📊 Running analytics update...")
        from analytics.manager import analyze_performance
        strategy = analyze_performance()
        print(f"[Master] ✓ Analytics updated. Top views: {strategy.get('top_views', 0)}")
        return True
    except Exception as e:
        print(f"[Master] Analytics update failed (non-fatal): {e}")
        return False


def run_short():
    """Publish one Short video"""
    try:
        print("\n[Master] 📱 Publishing Short video...")
        from orchestrator_short import run_short_pipeline
        result = run_short_pipeline(dry_run=False)
        if result and result.get("status") == "published":
            log_scheduled_publish("short", result.get("video_id", ""), result.get("title", ""))
            print(f"[Master] ✓ Short published: {result.get('url', '')}")
            return True
        else:
            print(f"[Master] Short pipeline returned: {result}")
            return False
    except Exception as e:
        print(f"[Master] Short failed: {e}")
        traceback.print_exc()
        return False


def run_long():
    """Publish one Long video"""
    try:
        print("\n[Master] 🎬 Publishing Long video...")
        from orchestrator_long import run_long_pipeline
        result = run_long_pipeline(dry_run=False, force=True)
        if result and result.get("status") == "published":
            log_scheduled_publish("long", result.get("video_id", ""), result.get("title", ""))
            print(f"[Master] ✓ Long video published: {result.get('url', '')}")
            return True
        else:
            print(f"[Master] Long pipeline returned: {result}")
            return False
    except Exception as e:
        print(f"[Master] Long failed: {e}")
        traceback.print_exc()
        return False


def main():
    now_utc = datetime.now(timezone.utc)
    print(f"\n{'='*60}")
    print(f"  MASTER RUNNER — {now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")

    # Read force flags from environment (set by workflow_dispatch inputs)
    force_short     = os.environ.get("FORCE_SHORT", "false").lower() == "true"
    force_long      = os.environ.get("FORCE_LONG", "false").lower() == "true"
    force_analytics = os.environ.get("FORCE_ANALYTICS", "false").lower() == "true"

    # ── 1. Print current schedule summary ─────────────────────────
    summary = get_schedule_summary()
    print(f"\n[Master] Schedule Status:")
    print(f"  Current time:   {summary['current_utc']}")
    print(f"  Day:            {summary['current_day']}")
    print(f"  Optimal slots:  {summary['optimal_slots_utc']} UTC")
    print(f"  Shorts today:   {summary['shorts_today']}/4")
    print(f"  Longs today:    {summary['longs_today']}")
    print(f"  Longs/week:     {summary['longs_this_week']}/4")
    print(f"  Short now?      {summary['should_publish_short']} — {summary['short_reason']}")
    print(f"  Long now?       {summary['should_publish_long']} — {summary['long_reason']}")

    actions_taken = []

    # ── 2. Daily analytics at 6 AM UTC ────────────────────────────
    if force_analytics or now_utc.hour == 6:
        print("\n[Master] ⏰ Analytics time (6AM UTC)")
        run_analytics()
        actions_taken.append("analytics")

    # ── 3. Publish Short if optimal time ──────────────────────────
    should_short, short_reason = should_publish_short_now()
    if force_short or should_short:
        reason_msg = "forced" if force_short else short_reason
        print(f"\n[Master] ✅ Publishing Short ({reason_msg})")
        success = run_short()
        actions_taken.append("short_success" if success else "short_failed")
    else:
        print(f"\n[Master] ⏭ Skipping Short: {short_reason}")

    # ── 4. Publish Long video if right day + time ──────────────────
    should_long, long_reason = should_publish_long_now()
    if force_long or should_long:
        reason_msg = "forced" if force_long else long_reason
        print(f"\n[Master] ✅ Publishing Long video ({reason_msg})")
        success = run_long()
        actions_taken.append("long_success" if success else "long_failed")
    else:
        print(f"\n[Master] ⏭ Skipping Long: {long_reason}")

    # ── 5. Summary ─────────────────────────────────────────────────
    print(f"\n{'='*60}")
    if not actions_taken:
        print("  STATUS: No action needed this hour ✓")
    else:
        print(f"  STATUS: Actions taken: {', '.join(actions_taken)}")
    print(f"{'='*60}\n")

    # Exit with error if a forced action failed
    if ("short_failed" in actions_taken and force_short) or \
       ("long_failed" in actions_taken and force_long):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
