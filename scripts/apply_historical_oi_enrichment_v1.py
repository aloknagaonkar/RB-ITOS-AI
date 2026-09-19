from pathlib import Path
import shutil

src = Path("backend/market_lab/historical_oi_enrichment_v1.py")
if not src.exists():
    raise SystemExit("Safe-stop: enrichment module not found in bundle root.")
print("Historical OI enrichment module is installed.")
print("It deliberately does not modify the frozen canonical 90-session source.")
