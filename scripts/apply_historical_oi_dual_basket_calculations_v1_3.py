from pathlib import Path
target=Path("backend/market_lab/historical_oi_build_job_v1.py")
adapter_target=Path("backend/market_lab/historical_oi_built_source_adapter_v1.py")
if not target.exists(): raise SystemExit("Safe-stop: historical_oi_build_job_v1.py not found.")
if not adapter_target.exists(): raise SystemExit("Safe-stop: historical_oi_built_source_adapter_v1.py not found.")
target.write_text(Path("backend/market_lab/historical_oi_build_job_v1_3.py").read_text(encoding="utf-8"),encoding="utf-8")
adapter_target.write_text(Path("backend/market_lab/historical_oi_built_source_adapter_v1_3.py").read_text(encoding="utf-8"),encoding="utf-8")
for script in ["scripts/apply_historical_oi_audit_calculations_v1_3.py","scripts/apply_historical_oi_audit_css_v1_3.py"]:
    p=Path(script);exec(compile(p.read_text(encoding="utf-8"),str(p),"exec"))
print("Applied Historical OI Dual-Basket Calculations V1.3.")
