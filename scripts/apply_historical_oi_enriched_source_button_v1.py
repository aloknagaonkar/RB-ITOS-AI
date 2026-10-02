from pathlib import Path
import re

P = Path("frontend/src/historicalOiResearch.tsx")
if not P.exists():
    raise SystemExit("Safe-stop: frontend/src/historicalOiResearch.tsx not found.")

text = P.read_text(encoding="utf-8")

if "setSource('ENRICHED')" in text:
    print("Enriched source button already present; no change needed.")
    raise SystemExit(0)

# Find the existing BUILT source-control button regardless of className/text formatting.
pat = re.compile(
    r"""<button\b(?P<attrs>[^>]*)onClick=\{\(\)\s*=>\s*setSource\(['"]BUILT['"]\)\}(?P<attrs2>[^>]*)>"""
    r"""(?P<body>.*?)</button>""",
    re.S,
)
m = pat.search(text)

if not m:
    # Also support onClick before className or arbitrary attribute ordering by scanning
    # complete button blocks and selecting the one containing setSource('BUILT').
    for candidate in re.finditer(r"<button\b[^>]*>.*?</button>", text, re.S):
        block = candidate.group(0)
        if re.search(r"""setSource\(\s*['"]BUILT['"]\s*\)""", block):
            m = candidate
            break

if not m:
    raise SystemExit(
        "Safe-stop: could not locate the existing BUILT source control. "
        "No frontend file was changed."
    )

built_block = m.group(0)

# Reuse the same surrounding styling convention as the existing controls.
# The class expression is explicit so ENRICHED gets the same active-state behavior.
enriched_button = (
    "\n"
    "        <button "
    "className={source==='ENRICHED'?'active':''} "
    "onClick={()=>setSource('ENRICHED')}>"
    "Enriched"
    "</button>"
)

text = text[:m.end()] + enriched_button + text[m.end():]

# Post-apply structural checks.
required = [
    "type Source='CANONICAL'|'BUILT'|'ENRICHED'",
    "setSource('ENRICHED')",
    "/api/live-shadow/replay-ops/historical-oi/enriched/sessions",
    "/api/live-shadow/replay-ops/historical-oi/enriched/rows",
]
missing = [x for x in required if x not in text]
if missing:
    raise SystemExit(
        "Safe-stop: ENRICHED backend wiring is incomplete in current JSX; "
        "not writing partial UI change. Missing: " + ", ".join(missing)
    )

P.write_text(text, encoding="utf-8")
print("Inserted Enriched source button into Historical OI Research.")
print("Backend endpoint wiring already present and verified.")
