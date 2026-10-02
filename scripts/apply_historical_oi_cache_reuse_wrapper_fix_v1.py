from pathlib import Path

P = Path("backend/market_lab/historical_oi_cache_reuse_rate_limit_v1.py")
if not P.exists():
    raise SystemExit("Safe-stop: target module not found")

text = P.read_text(encoding="utf-8")

marker = 'MODEL = "HISTORICAL_OI_CACHE_REUSE_RATE_LIMIT_V1"\nANALYTICAL_WINGS = 5\n'

helper = '''MODEL = "HISTORICAL_OI_CACHE_REUSE_RATE_LIMIT_V1"
ANALYTICAL_WINGS = 5


def _load_session_compatible(path: Path, session_date: str) -> dict[str, Any]:
    # Accept newer build-wrapper JSON and older single-session cache JSON.
    doc = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(doc, dict) and isinstance(doc.get("sessions"), list):
        matches = [
            s for s in doc["sessions"]
            if isinstance(s, dict) and str(s.get("session_date")) == session_date
        ]
    elif isinstance(doc, dict) and str(doc.get("session_date")) == session_date:
        matches = [doc]
    else:
        matches = []

    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one compatible session for {session_date}, found {len(matches)}"
        )

    session = matches[0]
    if str(session.get("status")) != "AVAILABLE":
        raise ValueError(
            f"Compatible session is not AVAILABLE for {session_date}: {session.get('status')}"
        )
    if not isinstance(session.get("rows"), list) or not session["rows"]:
        raise ValueError(f"Compatible session has no rows for {session_date}")

    return session
'''

if marker in text and "def _load_session_compatible" not in text:
    text = text.replace(marker, helper, 1)

old1 = "phase_a_session = _load_built(phase_a_source, session_date)"
new1 = "phase_a_session = _load_session_compatible(phase_a_source, session_date)"
if old1 in text:
    text = text.replace(old1, new1, 1)
elif new1 not in text:
    raise SystemExit("Safe-stop: phase A loader call not recognized")

old2 = "final_session = _load_built(final_source, session_date)"
new2 = "final_session = _load_session_compatible(final_source, session_date)"
if old2 in text:
    text = text.replace(old2, new2, 1)
elif new2 not in text:
    raise SystemExit("Safe-stop: final loader call not recognized")

text = text.replace(
    "from .historical_oi_enrichment_v1 import _load_built, _load_canonical, enrich_session, write_csv",
    "from .historical_oi_enrichment_v1 import _load_canonical, enrich_session, write_csv",
)

required = [
    "def _load_session_compatible",
    "phase_a_session = _load_session_compatible",
    "final_session = _load_session_compatible",
]
missing = [x for x in required if x not in text]
if missing:
    raise SystemExit("Safe-stop: post-check failed: " + ", ".join(missing))

P.write_text(text, encoding="utf-8")
print("Patched cache-reuse module to support wrapper and legacy single-session cache formats.")
