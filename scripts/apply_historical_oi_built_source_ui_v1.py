from pathlib import Path
exec(compile(Path("scripts/apply_historical_oi_built_api_v1.py").read_text(encoding="utf-8"),"apply_historical_oi_built_api_v1.py","exec"))
ui=Path("frontend/src/historicalOiResearch.tsx")
css=Path("frontend/src/historicalOiResearch.css")
if not ui.exists(): raise SystemExit("Safe-stop: historicalOiResearch.tsx not found")
ui.write_text(Path("frontend/src/historicalOiResearch.built-source-v1.tsx").read_text(encoding="utf-8"),encoding="utf-8")
append=Path("frontend/src/historicalOiResearch.built-source-v1.css").read_text(encoding="utf-8")
old=css.read_text(encoding="utf-8") if css.exists() else ""
if ".hoi-source-controls" not in old: css.write_text(old.rstrip()+"\n"+append+"\n",encoding="utf-8")
print("Applied Historical OI Built Source UI V1.")
