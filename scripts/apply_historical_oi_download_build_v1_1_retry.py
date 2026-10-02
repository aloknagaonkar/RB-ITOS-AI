from pathlib import Path

JOB=Path("backend/market_lab/historical_oi_build_job_v1.py")
PANEL=Path("frontend/src/historicalOiBuildPanel.tsx")
CSS=Path("frontend/src/historicalOiBuildPanel.css")

if not JOB.exists():
    raise SystemExit("Safe-stop: Historical OI Download / Build V1 must be applied first.")
if not PANEL.exists():
    raise SystemExit("Safe-stop: historicalOiBuildPanel.tsx not found.")

replacement=Path("backend/market_lab/historical_oi_build_job_v1_1.py").read_text(encoding="utf-8")
JOB.write_text(replacement,encoding="utf-8")

panel=Path("frontend/src/historicalOiBuildPanel.retry-v1-1.tsx").read_text(encoding="utf-8")
PANEL.write_text(panel,encoding="utf-8")

append=Path("frontend/src/historicalOiBuildPanel.retry-v1-1.css").read_text(encoding="utf-8")
existing=CSS.read_text(encoding="utf-8") if CSS.exists() else ""
if ".hoi-attempts" not in existing:
    CSS.write_text(existing.rstrip()+"\n"+append+"\n",encoding="utf-8")

print("Applied Historical OI Download / Build V1.1 retry hardening.")
