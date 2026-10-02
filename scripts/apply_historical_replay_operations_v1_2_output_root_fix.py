from pathlib import Path
import re

PATH = Path("backend/market_lab/historical_replay_operations_worker_v1.py")
text = PATH.read_text(encoding="utf-8")

if 'output_root="data/live-observation/replay"' in text:
    print("Replay Operations already writes V1.2 output to the canonical replay root.")
    raise SystemExit(0)

pattern = re.compile(
    r'run_day\(\s*session_date\s*,\s*'
    r'overwrite\s*=\s*overwrite\s*,\s*'
    r'progress\s*=\s*False\s*\)',
    re.MULTILINE,
)

replacement = (
    'run_day(\n'
    '            session_date,\n'
    '            output_root="data/live-observation/replay",\n'
    '            overwrite=overwrite,\n'
    '            progress=False,\n'
    '        )'
)

updated, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit(
        "Safe-stop: expected Replay Operations run_day(...) call was not found. "
        "No file was modified."
    )

PATH.write_text(updated, encoding="utf-8")
print("Replay Operations V1.2 output root fixed to data/live-observation/replay.")
