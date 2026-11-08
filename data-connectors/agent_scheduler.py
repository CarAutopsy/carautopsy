"""
CarAutopsy Agent Scheduler
Coordinates all agents. Run manually or via cron/APScheduler.
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))

def main():
    print(f"CarAutopsy Agent Run - {datetime.utcnow().isoformat()}")
    print("=" * 50)

    print("[Agent 2] Statutory Monitor...")
    try:
        from statutory_feeds.statutory_monitor import StatutoryMonitor
        repo_root = Path(__file__).resolve().parent.parent
        monitor = StatutoryMonitor(repo_root)
        results = monitor.run_all()
        for r in results:
            print(f"  {r['source']}: {r['status']}")
    except Exception as e:
        print(f"  Error: {e}")

    print("[Validation] Catalog check...")
    import subprocess
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run([sys.executable, str(repo_root / "scripts" / "validate_catalog.py")], capture_output=True, text=True)
    print(result.stdout if result.stdout else "  (no output)")

    print("=" * 50)
    print("Agent run complete.")

if __name__ == "__main__":
    main()
