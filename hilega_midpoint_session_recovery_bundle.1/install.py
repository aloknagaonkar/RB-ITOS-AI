"""Install scoped recovery changes with source rollback on failed validation."""
from pathlib import Path
from datetime import datetime, timezone
import shutil
import subprocess
import sys
import os

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parent


def main():
    backup = ROOT / "data/backups" / ("shadow-session-recovery-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    installed = []
    try:
        for source in sorted((BUNDLE / "files").rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(BUNDLE / "files")
            target = ROOT / relative
            existed = target.exists()
            if existed:
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            installed.append((target, relative, existed))
        commands = [
            [sys.executable, "-m", "pytest", "-q", "tests/test_shadow_session_recovery.py",
             "tests/test_hilega_directional_bootstrap_recovery_v1.py",
             "tests/test_midpoint_health_audit_inspect.py", "tests/test_hilega_phase7d3_market_evidence_v1.py",
             "tests/test_midpoint_continuous_system_health.py", "tests/test_midpoint_historical_health_replay.py",
             "tests/test_hilega_directional_live_shadow_ui_v1.py"],
            ["npm", "--prefix", "frontend", "run", "build"],
            ["git", "diff", "--check"],
        ]
        for command in commands:
            print("Running:", " ".join(command), flush=True)
            env = dict(os.environ)
            env["PYTHONPATH"] = str(ROOT / "backend") + os.pathsep + str(ROOT)
            subprocess.run(command, cwd=ROOT, check=True, env=env)
    except Exception:
        for target, relative, existed in reversed(installed):
            if existed:
                shutil.copy2(backup / relative, target)
            else:
                target.unlink(missing_ok=True)
        print("STOP: validation failed; source restored. Frontend dist may require rebuilding.")
        raise
    print("PASS: recovery changes installed. Restart required; no order APIs used.")
    print("Backup:", backup)


if __name__ == "__main__":
    main()
