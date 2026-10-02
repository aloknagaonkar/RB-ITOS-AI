from pathlib import Path
JOB=Path("backend/market_lab/historical_oi_build_job_v1.py")
PANEL=Path("frontend/src/historicalOiBuildPanel.tsx")
CSS=Path("frontend/src/historicalOiBuildPanel.css")
if not JOB.exists() or not PANEL.exists():
    raise SystemExit("Safe-stop: apply Historical OI Download / Build V1 first.")
JOB.write_text(Path("backend/market_lab/historical_oi_build_job_v1_2.py").read_text(encoding="utf-8"),encoding="utf-8")
PANEL.write_text(Path("frontend/src/historicalOiBuildPanel.quality-v1-2.tsx").read_text(encoding="utf-8"),encoding="utf-8")
append=Path("frontend/src/historicalOiBuildPanel.quality-v1-2.css").read_text(encoding="utf-8")
old=CSS.read_text(encoding="utf-8") if CSS.exists() else ""
if ".hoi-contract-warning" not in old:
    CSS.write_text(old.rstrip()+"\n"+append+"\n",encoding="utf-8")
print("Applied Historical OI Download / Build V1.2 data-quality hardening.")
