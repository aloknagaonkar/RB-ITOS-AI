from pathlib import Path
import re

UI = Path("frontend/src/historicalOiResearch.tsx")
if not UI.exists():
    raise SystemExit("Safe-stop: frontend/src/historicalOiResearch.tsx not found.")

text = UI.read_text(encoding="utf-8")

m = re.search(r"function\s+Audit\s*\(\s*\{\s*row\s*\}\s*:\s*\{\s*row\s*:\s*Row\s*\}\s*\)\s*\{", text)
if not m:
    raise SystemExit("Safe-stop: Audit({row}:{row:Row}) function not found.")

audit_start = m.end()

required_decls = [
    "const movingChecks=movingValidation(row)",
    "const fixedChecks=fixedValidation(row)",
    "const fixedCePct=",
    "const fixedPePct=",
    "const fixedImbalance=",
    "const fixedBasePcr=",
    "const fixedCurrentPcr=",
    "const fixedPcrChange=",
]

scope_preview = text[audit_start:audit_start+6000]
missing = [x for x in required_decls if x not in scope_preview]

if missing:
    block = '''
  const fixedImbalance =
    row.f_imbalance ??
    ((row.f_pe_delta != null && row.f_ce_delta != null)
      ? Number(row.f_pe_delta) - Number(row.f_ce_delta)
      : null)

  const fixedBasePcr =
    row.f_pcr_baseline ??
    ((row.fixed_ce_oi_baseline_0920 != null &&
      row.fixed_pe_oi_baseline_0920 != null &&
      Number(row.fixed_ce_oi_baseline_0920) !== 0)
      ? Number(row.fixed_pe_oi_baseline_0920) /
        Number(row.fixed_ce_oi_baseline_0920)
      : null)

  const fixedCurrentPcr =
    row.f_pcr ??
    ((row.fixed_ce_oi != null &&
      row.fixed_pe_oi != null &&
      Number(row.fixed_ce_oi) !== 0)
      ? Number(row.fixed_pe_oi) / Number(row.fixed_ce_oi)
      : null)

  const fixedPcrChange =
    row.f_pcr_change ??
    ((fixedBasePcr != null && fixedCurrentPcr != null)
      ? Number(fixedCurrentPcr) - Number(fixedBasePcr)
      : null)

  const fixedCePct =
    row.f_ce_pct ??
    ((row.fixed_ce_oi_baseline_0920 != null &&
      row.f_ce_delta != null &&
      Number(row.fixed_ce_oi_baseline_0920) !== 0)
      ? Number(row.f_ce_delta) /
        Number(row.fixed_ce_oi_baseline_0920) * 100
      : null)

  const fixedPePct =
    row.f_pe_pct ??
    ((row.fixed_pe_oi_baseline_0920 != null &&
      row.f_pe_delta != null &&
      Number(row.fixed_pe_oi_baseline_0920) !== 0)
      ? Number(row.f_pe_delta) /
        Number(row.fixed_pe_oi_baseline_0920) * 100
      : null)

  const movingChecks=movingValidation(row)
  const fixedChecks=fixedValidation(row)
'''
    text = text[:audit_start] + "\n" + block + text[audit_start:]

UI.write_text(text, encoding="utf-8")

updated = UI.read_text(encoding="utf-8")
audit_match = re.search(r"function\s+Audit\s*\(\s*\{\s*row\s*\}\s*:\s*\{\s*row\s*:\s*Row\s*\}\s*\)\s*\{", updated)
if not audit_match:
    raise SystemExit("Post-check failed: Audit function missing.")

scope_preview = updated[audit_match.end():audit_match.end()+6000]
still_missing = [x for x in required_decls if x not in scope_preview]
if still_missing:
    raise SystemExit("Post-check failed; declarations still missing: " + ", ".join(still_missing))

print("Applied Historical OI Card Validation V1.2 scope fix.")
for item in required_decls:
    print("  OK", item)
