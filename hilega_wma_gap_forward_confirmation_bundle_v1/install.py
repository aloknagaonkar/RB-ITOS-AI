from __future__ import annotations
import shutil, subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
BUNDLE=Path(__file__).resolve().parent
FILES=BUNDLE/"files"
STAMP=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
BACKUP=ROOT/"data"/"backups"/f"hilega-wma-forward-{STAMP}"
COPIES=[
 "backend/market_lab/hilega_wma_gap_historical_v1.py",
 "backend/market_lab/hilega_historical_ui_api_v1.py",
 "scripts/hilega_wma_gap_forward_publisher.py",
 "scripts/start_hilega_wma_gap_forward_publisher.sh",
 "scripts/stop_hilega_wma_gap_forward_publisher.sh",
 "scripts/status_hilega_wma_gap_forward_publisher.sh",
 "tests/test_hilega_wma_gap_forward_publisher.py",
]

def backup(path):
    if path.exists():
        target=BACKUP/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
def restore(paths):
    for path in reversed(paths):
        saved=BACKUP/path.relative_to(ROOT)
        if saved.exists():path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(saved,path)
        elif path.exists():path.unlink()
def run(cmd):
    print("Running:"," ".join(map(str,cmd)));subprocess.run(cmd,cwd=ROOT,check=True)

def main():
    restart=ROOT/"scripts/restart.sh"
    touched=[ROOT/x for x in COPIES]+[restart]
    for path in touched:backup(path)
    try:
        for item in COPIES:
            source,target=FILES/item,ROOT/item;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        for name in ("hilega_wma_gap_forward_publisher.py","start_hilega_wma_gap_forward_publisher.sh","stop_hilega_wma_gap_forward_publisher.sh","status_hilega_wma_gap_forward_publisher.sh"):
            (ROOT/"scripts"/name).chmod(0o755)
        text=restart.read_text()
        marker="HILEGA WMA-GAP FORWARD-CONFIRMATION PUBLISHER"
        if marker not in text:
            text += "\n# ===== HILEGA WMA-GAP FORWARD-CONFIRMATION PUBLISHER =====\n\"$ROOT/scripts/stop_hilega_wma_gap_forward_publisher.sh\" || true\n\"$ROOT/scripts/start_hilega_wma_gap_forward_publisher.sh\"\n# ===== END HILEGA WMA-GAP FORWARD-CONFIRMATION PUBLISHER =====\n"
            restart.write_text(text)
        python=str(ROOT/".venv/bin/python")
        run([python,"-m","pytest","-q","tests/test_hilega_wma_gap_forward_publisher.py","tests/test_hilega_wma_gap_historical_v1.py","tests/test_hilega_historical_ui_api_v1.py","tests/test_backtest_hilega_wma_gap_490.py"])
        run([python,"-m","py_compile","scripts/hilega_wma_gap_forward_publisher.py","backend/market_lab/hilega_wma_gap_historical_v1.py","backend/market_lab/hilega_historical_ui_api_v1.py"])
        run(["bash","-n","scripts/start_hilega_wma_gap_forward_publisher.sh","scripts/stop_hilega_wma_gap_forward_publisher.sh","scripts/status_hilega_wma_gap_forward_publisher.sh","scripts/restart.sh"])
        run(["npm","--prefix","frontend","run","build"])
        run(["git","diff","--check"])
    except Exception as exc:
        restore(touched);print(f"STOP: validation failed; installed source restored: {exc}");return 1
    print("PASS: Hilega WMA-gap automatic forward confirmation installed.")
    print("Frozen 490-session evidence remains untouched. Restart is required.")
    print("Backup:",BACKUP);return 0
if __name__=="__main__":raise SystemExit(main())
