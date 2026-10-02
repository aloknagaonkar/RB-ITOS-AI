from pathlib import Path

p = Path("frontend/src/App.tsx")
text = p.read_text(encoding="utf-8")

required = [
    "import HistoricalReplay from './historicalReplay'",
    "'Historical replay'",
    "tab==='Historical replay'",
    "<HistoricalReplay/>",
]

missing = [item for item in required if item not in text]
if missing:
    raise SystemExit("VERIFY FAILED: missing " + ", ".join(missing))

print("Historical Replay frontend integration verification passed.")
