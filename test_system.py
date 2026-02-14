#!/usr/bin/env python
"""
Quick test to validate the system works.
"""
import sys
import os
from pathlib import Path

# Add project root to path
proj_root = Path(__file__).parent
sys.path.insert(0, str(proj_root))

def test_imports():
    """Test all imports work correctly."""
    print("Testing imports...")
    try:
        from yt_auto.config import load_config
        from yt_auto.state import StateStore
        from yt_auto.llm import generate_quiz_item
        from yt_auto.manager import ContentAnalyzer, StrategyOptimizer, RiskManager
        from yt_auto.scheduler import PublishingSchedule, RateLimiter
        print("✓ All imports successful")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False

def test_config():
    """Test config loading."""
    print("\nTesting config...")
    try:
        from yt_auto.config import load_config
        cfg = load_config()
        print(f"✓ Config loaded")
        print(f"  - Project root: {cfg.project_root}")
        print(f"  - Output dir: {cfg.out_dir}")
        print(f"  - State file: {cfg.state_path}")
        return True
    except Exception as e:
        print(f"✗ Config failed: {e}")
        return False

def test_state():
    """Test state management."""
    print("\nTesting state management...")
    try:
        from yt_auto.config import load_config
        from yt_auto.state import StateStore
        
        cfg = load_config()
        state = StateStore(cfg.state_path)
        
        # Test basic operations
        state.set_bootstrapped(True)
        assert state.is_bootstrapped(), "Bootstrap flag not set"
        
        state.add_used_question("Test question?", "Test answer", "2025-01-01")
        is_dup = state.is_duplicate_question("Test question?", days_window=15)
        assert is_dup, "Duplicate detection failed"
        
        state.save()
        print("✓ State management works")
        return True
    except Exception as e:
        print(f"✗ State test failed: {e}")
        return False

def test_scheduler():
    """Test scheduling."""
    print("\nTesting scheduler...")
    try:
        from yt_auto.config import load_config
        from yt_auto.scheduler import PublishingSchedule, RateLimiter
        
        cfg = load_config()
        schedule = PublishingSchedule(cfg)
        rate_limiter = RateLimiter(cfg)
        
        stats = schedule.get_daily_stats()
        print(f"✓ Scheduling works")
        print(f"  - Shorts today: {stats['shorts_published_today']}")
        return True
    except Exception as e:
        print(f"✗ Scheduler test failed: {e}")
        return False

def test_manager():
    """Test manager."""
    print("\nTesting manager...")
    try:
        from yt_auto.config import load_config
        from yt_auto.manager import ContentAnalyzer, StrategyOptimizer, RiskManager
        
        cfg = load_config()
        analyzer = ContentAnalyzer(cfg)
        optimizer = StrategyOptimizer(cfg, analyzer)
        risk_mgr = RiskManager(cfg)
        
        recs = analyzer.get_recommendations()
        print(f"✓ Manager works")
        print(f"  - Best templates: {recs['best_templates']}")
        return True
    except Exception as e:
        print(f"✗ Manager test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("=" * 50)
    print("YouTube Shorts AutoGen - System Test")
    print("=" * 50)
    
    tests = [
        test_imports,
        test_config,
        test_state,
        test_scheduler,
        test_manager,
    ]
    
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"✗ Test error: {e}")
            results.append(False)
    
    print("\n" + "=" * 50)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 50)
    
    return 0 if all(results) else 1

if __name__ == "__main__":
    sys.exit(main())
