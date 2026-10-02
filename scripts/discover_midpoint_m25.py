#!/usr/bin/env python3
from pathlib import Path
import json, re, subprocess, sys

ROOT = Path.cwd()
OUT = Path("/tmp/midpoint-m25-discovery.txt")

def section(title):
    return ["", "=" * 88, title, "=" * 88]

def run(cmd):
    try:
        p = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=30)
        return (p.stdout + ("\n" + p.stderr if p.stderr else "")).strip()
    except Exception as e:
        return f"ERROR: {e}"

lines = []
lines += section("MIDPOINT M2.5 DISCOVERY")
lines += [
    "Goal: reuse existing exact option-observation infrastructure for Midpoint.",
    "Safety: read-only discovery; no files are modified.",
]

# 1) Find likely code paths
patterns = [
    "Five independent",
    "entry_premium",
    "exit_premium",
    "instrument_key",
    "MFE",
    "MAE",
    "option_intent",
    "option_chain",
    "ATM-2",
    "ACTIVE / EXIT PENDING",
]
lines += section("RELEVANT SOURCE MATCHES")
for pat in patterns:
    out = run(["grep", "-RIn", "--exclude-dir=.git", "--exclude-dir=node_modules",
               "--exclude=*.bak", pat, "backend", "frontend", "scripts", "tests"])
    hits = [x for x in out.splitlines() if x.strip()]
    lines.append(f"\n### {pat}")
    lines.extend(hits[:40] if hits else ["(none)"])

# 2) Find Hilega option related files
lines += section("HILEGA OPTION-RELATED FILES")
out = run(["find", "backend", "frontend", "scripts", "tests", "-type", "f"])
cands = []
for name in out.splitlines():
    low = name.lower()
    if ("hilega" in low and any(k in low for k in ("option", "dashboard", "shadow", "ui"))) or \
       ("option" in low and "shadow" in low):
        cands.append(name)
lines.extend(cands[:120] if cands else ["(none)"])

# 3) Inspect likely endpoint/source snippets using grep context
queries = [
    ("backend", "entry_premium"),
    ("backend", "instrument_key"),
    ("backend", "mfe"),
    ("backend", "mae"),
    ("backend", "option_contract"),
    ("backend", "option_chain"),
    ("frontend", "entry_premium"),
    ("frontend", "MFE"),
]
lines += section("CONTEXT AROUND IMPORTANT FIELDS")
for base, pat in queries:
    out = run(["grep", "-RIn", "-A8", "-B8",
               "--exclude-dir=.git", "--exclude-dir=node_modules",
               "--exclude=*.bak", pat, base])
    hits = out.splitlines()
    lines.append(f"\n### {base}: {pat}")
    lines.extend(hits[:120] if hits else ["(none)"])

# 4) Midpoint current API/source signatures
lines += section("MIDPOINT CURRENT UI/API SIGNATURES")
files = [
    Path("backend/market_lab/midpoint_strategy/live_shadow_ui.py"),
    Path("frontend/src/midpointStrategyShadow.tsx"),
]
for p in files:
    lines.append(f"\n### {p}")
    if not p.exists():
        lines.append("(missing)")
        continue
    text = p.read_text(errors="replace")
    for needle in [
        "def _audit_ui_detail",
        "def _presentation_for_replay",
        "@router.get",
        "option",
        "latest_event",
        "latest_entry",
        "LiveContinuationPanel",
        "AuditDetail",
    ]:
        for m in re.finditer(re.escape(needle), text, re.I):
            start = max(0, text.rfind("\n", 0, m.start()-500))
            end = text.find("\n", m.end()+1200)
            if end < 0: end = min(len(text), m.end()+1200)
            snippet = text[start:end].strip()
            lines.append(f"\n-- {needle} --\n{snippet[:1800]}")
            break

# 5) Query local APIs if running
lines += section("LOCAL API DISCOVERY")
api_urls = [
    "http://127.0.0.1:8123/api/live-shadow/midpoint-strategy/status",
    "http://127.0.0.1:8123/api/live-shadow/midpoint-strategy/historical/session?session_date=2026-09-24",
]
for url in api_urls:
    lines.append(f"\n### {url}")
    out = run(["curl", "-sS", "--max-time", "5", url])
    if not out:
        lines.append("(no response)")
        continue
    try:
        obj = json.loads(out)
        if "minutes" in obj:
            mins = obj.get("minutes") or []
            active = [m for m in mins if m.get("presentation")]
            summary = {
                "session_date": obj.get("session_date"),
                "minute_count": obj.get("minute_count"),
                "timeline_count": len(obj.get("timeline") or []),
                "presentation_rows": len(active),
                "sample_presentation": active[0].get("presentation") if active else None,
            }
            lines.append(json.dumps(summary, indent=2, default=str))
        else:
            # redact to useful subset
            keep = {k: obj.get(k) for k in [
                "model","mode","audit_record_count","session_dates",
                "family_b_state","latest_event","latest_entry","latest_terminal","safety"
            ] if k in obj}
            lines.append(json.dumps(keep, indent=2, default=str)[:8000])
    except Exception:
        lines.append(out[:8000])

# 6) Candidate underlying/option evidence files
lines += section("OPTION DATA / EVIDENCE FILE CANDIDATES")
out = run(["find", "data", "-type", "f"])
files = []
for name in out.splitlines():
    low = name.lower()
    if any(k in low for k in ("option", "chain", "premium", "instrument")):
        files.append(name)
lines.extend(files[:150] if files else ["(none)"])

# 7) Requirements captured
lines += section("M2.5 REQUIRED UI FIELDS")
lines += [
    "TOP HEADER:",
    "- Session / trading date",
    "- Latest market-data timestamp",
    "- Latest strategy/audit timestamp",
    "- Last UI refresh timestamp",
    "- Data age / freshness",
    "- Source: LIVE / HISTORICAL / FORWARD_OOS / V57 parity",
    "",
    "OPTION BASKET AT ENTRY:",
    "- Five contracts frozen at entry: ATM-2, ATM-1, ATM, ATM+1, ATM+2",
    "- Option side must match intent: BUY PE -> PE basket, BUY CE -> CE basket",
    "- Expiry, ATM-at-entry, strike, instrument key, entry time, entry premium",
    "",
    "PROGRESSION:",
    "- Current/latest premium",
    "- Current/latest timestamp",
    "- P&L points and %",
    "- MFE and MAE",
    "- Exit time/premium when closed",
    "- Status ACTIVE / EXIT PENDING / CLOSED",
    "- Historical: values as-of inspected replay minute, not future-leaked final values",
    "- Live: update as new market data arrives",
    "",
    "SAFETY:",
    "- Observation only",
    "- No orders",
    "- No paper orders",
    "- No quantity",
    "- No change to B/E signal semantics",
    "- Do not fabricate option contracts or premiums",
]

OUT.write_text("\n".join(lines))
print(f"DISCOVERY REPORT: {OUT}")
print(f"SIZE: {OUT.stat().st_size} bytes")
print()
print("Paste/upload the report file, or run:")
print("  sed -n '1,260p' /tmp/midpoint-m25-discovery.txt")
