from pathlib import Path

P = Path("backend/market_lab/historical_oi_canonical_90_orchestrator_v1.py")
text = P.read_text(encoding="utf-8")

old_import = "from .historical_oi_auto_enrichment_v1 import run_auto_enrichment"
new_import = "from .historical_oi_cache_reuse_rate_limit_v1 import run_cache_reuse_enrichment"
if old_import in text:
    text = text.replace(old_import, new_import, 1)
elif new_import not in text:
    raise SystemExit("Safe-stop: orchestrator enrichment import not recognized")

old_call = """built = run_auto_enrichment(
                session_date=d,
                expiry=resolved["expiry"],
                canonical_path=canonical_path,
            )"""
new_call = """built = run_cache_reuse_enrichment(
                session_date=d,
                expiry=resolved["expiry"],
                canonical_path=canonical_path,
            )"""
if old_call in text:
    text = text.replace(old_call, new_call, 1)
elif new_call not in text:
    raise SystemExit("Safe-stop: orchestrator enrichment call not recognized")

P.write_text(text, encoding="utf-8")
print("Canonical-90 orchestrator now uses cache-reuse/rate-limit-safe enrichment.")
