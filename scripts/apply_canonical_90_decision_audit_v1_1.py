from pathlib import Path

P = Path("backend/market_lab/historical_oi_canonical_decision_audit_v1.py")
if not P.exists():
    raise SystemExit("Safe-stop: decision audit module not found")

text = P.read_text(encoding="utf-8")

old_hdata = """def hdata(row,h):
    mh=row.get("moving_horizons") or {}
    x=mh.get(str(h),mh.get(h))
    return x if isinstance(x,dict) else None
"""
new_hdata = """def hdata(row,h):
    mh=row.get("moving_horizons") or {}
    # Real enriched schema stores keys as '5m'/'10m'/'15m'.
    # Keep compatibility with older synthetic/tests using '5' or integer keys.
    x=mh.get(f"{h}m", mh.get(str(h), mh.get(h)))
    return x if isinstance(x,dict) else None
"""
if old_hdata in text:
    text = text.replace(old_hdata, new_hdata, 1)
elif new_hdata not in text:
    raise SystemExit("Safe-stop: hdata shape not recognized")

# Insert canonical-date loader before run_population.
marker = "def run_population(enrichment_root,futures_csv,output_root,only_dates=None):\n"
helper = """def load_canonical_dates(path):
    p=Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Canonical session source not found: {p}")
    dates=set()
    with p.open(newline="",encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            d=str(r.get("session_date") or "").strip()
            if d: dates.add(d)
    if not dates:
        raise ValueError(f"No canonical session_date values in {p}")
    return dates

def run_population(enrichment_root,futures_csv,output_root,only_dates=None,
                   canonical_csv="data/historical-evidence/oi-pattern-library-90d-historical-only-v1.csv"):
"""
if marker in text:
    text = text.replace(marker, helper, 1)
elif "def load_canonical_dates(" not in text:
    raise SystemExit("Safe-stop: run_population marker not recognized")

old_ds = """    ds=[d for d in sorted(er.iterdir()) if d.is_dir() and (d/"enriched.json").exists()]
    if only_dates: ds=[d for d in ds if d.name in only_dates]
"""
new_ds = """    canonical_dates=load_canonical_dates(canonical_csv)
    ds=[d for d in sorted(er.iterdir()) if d.is_dir() and (d/"enriched.json").exists() and d.name in canonical_dates]
    if only_dates: ds=[d for d in ds if d.name in only_dates]
"""
if old_ds in text:
    text = text.replace(old_ds, new_ds, 1)
elif new_ds not in text:
    raise SystemExit("Safe-stop: session discovery shape not recognized")

old_arg = """    p.add_argument("--output-root",default="data/historical-evidence/canonical-decision-audit-v1")
    p.add_argument("--date",action="append")
"""
new_arg = """    p.add_argument("--output-root",default="data/historical-evidence/canonical-decision-audit-v1")
    p.add_argument("--canonical-csv",default="data/historical-evidence/oi-pattern-library-90d-historical-only-v1.csv")
    p.add_argument("--date",action="append")
"""
if old_arg in text:
    text = text.replace(old_arg, new_arg, 1)

old_call = """    print(json.dumps(run_population(a.enrichment_root,a.futures_csv,a.output_root,set(a.date) if a.date else None),indent=2))
"""
new_call = """    print(json.dumps(run_population(a.enrichment_root,a.futures_csv,a.output_root,set(a.date) if a.date else None,a.canonical_csv),indent=2))
"""
if old_call in text:
    text = text.replace(old_call, new_call, 1)
elif new_call not in text:
    raise SystemExit("Safe-stop: main run_population call not recognized")

required = [
    'mh.get(f"{h}m"',
    "def load_canonical_dates",
    "d.name in canonical_dates",
    "--canonical-csv",
]
missing = [x for x in required if x not in text]
if missing:
    raise SystemExit("Safe-stop: post-check failed: " + ", ".join(missing))

P.write_text(text, encoding="utf-8")
print("Patched real enriched moving_horizons schema + exact canonical population filter.")
