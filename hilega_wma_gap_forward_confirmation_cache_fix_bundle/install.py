from __future__ import annotations
import shutil, subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = Path(__file__).resolve().parent
FILES = BUNDLE / "files"
STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
BACKUP = ROOT / "data" / "backups" / f"hilega-wma-forward-cache-fix-{STAMP}"
COPIES = [
    "scripts/hilega_wma_gap_forward_publisher.py",
    "scripts/research_hilega_alignment_points_490.py",
    "scripts/validate_hilega_wma_delayed_confirmation.py",
    "tests/test_hilega_wma_gap_forward_publisher.py",
]

def backup(path):
    if path.exists():
        target = BACKUP / path.relative_to(ROOT); target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, target)

def restore(paths):
    for path in reversed(paths):
        saved = BACKUP / path.relative_to(ROOT)
        if saved.exists(): path.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(saved, path)
        elif path.exists(): path.unlink()

def run(command):
    print("Running:", " ".join(map(str, command))); subprocess.run(command, cwd=ROOT, check=True)

def main():
    touched = [ROOT / item for item in COPIES]
    for path in touched: backup(path)
    try:
        for item in COPIES:
            source, target = FILES / item, ROOT / item; target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
        (ROOT / COPIES[0]).chmod(0o755)
        python = str(ROOT / ".venv/bin/python")
        run([python, "-m", "pytest", "-q", "tests/test_hilega_wma_gap_forward_publisher.py", "tests/test_hilega_wma_gap_historical_v1.py", "tests/test_hilega_historical_ui_api_v1.py", "tests/test_backtest_hilega_wma_gap_490.py"])
        run([python, "-m", "py_compile", "scripts/hilega_wma_gap_forward_publisher.py",
             "scripts/research_hilega_alignment_points_490.py",
             "scripts/validate_hilega_wma_delayed_confirmation.py"])
        run(["git", "diff", "--check"])
    except Exception as exc:
        restore(touched); print(f"STOP: validation failed; installed source restored: {exc}"); return 1
    print("PASS: Hilega forward publisher recorded-cache correction installed.")
    print("Completed live one-minute evidence now materializes the replay cache.")
    print("Frozen 490-session evidence, live strategy and orders remain untouched.")
    print("Backup:", BACKUP); return 0

if __name__ == "__main__": raise SystemExit(main())
