from pathlib import Path
from datetime import datetime, timezone
import os
import shutil
import subprocess
import sys

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parent
FILES = ["scripts/materialize_midpoint_forward_market_data.py",
         "tests/test_midpoint_recovery_contract_guard.py"]


def main():
    backup = ROOT / "data/backups" / ("midpoint-october-recovery-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    installed = []
    try:
        for relative in FILES:
            target = ROOT / relative
            existed = target.exists()
            if existed:
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(BUNDLE / "files" / relative, target)
            installed.append((target, relative, existed))
        env = dict(os.environ, PYTHONPATH=str(ROOT / "backend") + os.pathsep + str(ROOT))
        for command in ([sys.executable, "-m", "pytest", "-q", "tests/test_midpoint_recovery_contract_guard.py"],
                        [sys.executable, "-m", "py_compile", FILES[0]],
                        ["git", "diff", "--check"]):
            print("Running:", " ".join(command), flush=True)
            subprocess.run(command, cwd=ROOT, env=env, check=True)
    except Exception:
        for target, relative, existed in reversed(installed):
            if existed:
                shutil.copy2(backup / relative, target)
            else:
                target.unlink(missing_ok=True)
        raise
    print("PASS: October recovery contract guard installed. No restart or order dispatch.")
    print("Backup:", backup)


if __name__ == "__main__":
    main()
