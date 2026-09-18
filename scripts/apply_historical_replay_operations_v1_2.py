from pathlib import Path

PATH = Path("backend/market_lab/historical_replay_operations_worker_v1.py")

text = PATH.read_text(encoding="utf-8")

old_import = "from .historical_replay_day_v1_1 import run_day"
new_import = "from .historical_replay_day_v1_2 import run_day"

if new_import in text:
    print("Replay Operations already uses Historical Replay V1.2.")
elif old_import in text:
    text = text.replace(old_import, new_import, 1)
    PATH.write_text(text, encoding="utf-8")
    print("Replay Operations switched from Historical Replay V1.1 to V1.2.")
else:
    raise SystemExit(
        "Safe-stop: expected V1.1 run_day import not found in "
        "historical_replay_operations_worker_v1.py"
    )
