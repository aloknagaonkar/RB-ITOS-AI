from pathlib import Path
src=Path("frontend/src/historicalOiResearch.tsx")
css=Path("frontend/src/historicalOiResearch.css")
new=Path("frontend/src/historicalOiResearch.audit-v1.tsx")
if not src.exists():
    raise SystemExit("Safe-stop: frontend/src/historicalOiResearch.tsx not found. Apply Historical OI Research UI V1 first.")
src.write_text(new.read_text(encoding="utf-8"),encoding="utf-8")
append=Path("frontend/src/historicalOiResearch.audit-v1.css").read_text(encoding="utf-8")
existing=css.read_text(encoding="utf-8") if css.exists() else ""
if ".hoi-audit-grid" not in existing:
    css.write_text(existing.rstrip()+"\n"+append+"\n",encoding="utf-8")
print("Applied Historical OI audit detail V1.")
