from pathlib import Path

tsx = Path("frontend/src/historicalReplay.tsx").read_text(encoding="utf-8")
css = Path("frontend/src/historicalReplay.css").read_text(encoding="utf-8")

required_tsx = [
    "type ProgressItem",
    "function buildProgress",
    "function TradeSummary",
    "Chronological · audit + lifecycle events",
    "FUTURES_ALIGNMENT_CHECKED",
    "TRADE_CLOSED",
]
required_css = [
    "HISTORICAL_REPLAY_AUDIT_READABILITY_V1_1",
    ".hr-trade-summary",
    ".hr-life-detail",
]

missing = [x for x in required_tsx if x not in tsx] + [x for x in required_css if x not in css]
if missing:
    raise SystemExit("VERIFY FAILED: missing " + ", ".join(missing))

print("Historical Replay audit-readability verification passed.")
