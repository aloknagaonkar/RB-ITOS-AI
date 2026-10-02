from pathlib import Path

tsx = Path("frontend/src/historicalReplay.tsx").read_text(encoding="utf-8")
css = Path("frontend/src/historicalReplay.css").read_text(encoding="utf-8")

required_tsx = [
    "function explainProgressItem",
    "function terminalExplanation",
    "function TerminalPanel",
    "display_result?:string",
    "Reason</span>",
    "Next</span>",
    "C2_ELIGIBILITY",
    "requires ${futuresRequirement(direction)}",
]
required_css = [
    "HISTORICAL_REPLAY_EXPLAINABILITY_V1_2",
    ".hr-terminal",
    ".hr-life-explain",
    ".hr-life-label",
]

missing = [x for x in required_tsx if x not in tsx] + [x for x in required_css if x not in css]
if missing:
    raise SystemExit("VERIFY FAILED: missing " + ", ".join(missing))

print("Historical Replay Explainability V1.2 verification passed.")
