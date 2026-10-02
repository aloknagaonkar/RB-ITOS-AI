#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOTS = [Path("backend"), Path("frontend/src")]
PATTERNS = {
    "hilega": re.compile(r"hilega|milega", re.I),
    "midpoint": re.compile(r"midpoint", re.I),
    "historical": re.compile(r"historical|replay", re.I),
    "audit": re.compile(r"audit|inspect", re.I),
    "api_routes": re.compile(r"@(?:app|router)\.(?:get|post)|/api/", re.I),
    "session_date": re.compile(r"session_date|sessionDate|selectedDate", re.I),
}
MAX_FILE_BYTES = 2_000_000
MAX_SNIPPETS_PER_FILE = 20

def iter_files():
    exts = {".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".scss"}
    for root in ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                try:
                    if p.stat().st_size <= MAX_FILE_BYTES:
                        yield p
                except OSError:
                    continue

def classify(text):
    return [name for name, pat in PATTERNS.items() if pat.search(text)]

def snippets(text):
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        cats = classify(line)
        if cats:
            out.append((i, cats, line.rstrip()))
    return out[:MAX_SNIPPETS_PER_FILE]

def main():
    candidates = []
    for p in iter_files():
        try:
            text = p.read_text(errors="replace")
        except Exception:
            continue
        cats = classify(text)
        if cats:
            candidates.append((p, cats, text))

    candidates.sort(
        key=lambda x: (
            not ("hilega" in x[1] and "midpoint" in x[1]),
            not ("hilega" in x[1] and "audit" in x[1]),
            str(x[0]),
        )
    )

    print("MIDPOINT M1 — HILEGA REUSE PRE-FLIGHT")
    print("=" * 110)
    print("READ-ONLY: no files changed.\n")

    print("===== CANDIDATE FILES =====")
    for p, cats, _ in candidates:
        print(f"{str(p):90} {','.join(cats)}")

    print("\n===== HIGH-VALUE SNIPPETS =====")
    shown = 0
    for p, cats, text in candidates:
        if not ({"hilega", "midpoint", "historical", "audit"} & set(cats)):
            continue
        print(f"\n--- {p} ---")
        for lineno, lc, line in snippets(text):
            print(f"{lineno:5} [{','.join(lc)}] {line[:240]}")
        shown += 1
        if shown >= 25:
            break

    print("\n===== FRONTEND COMPONENT / ROUTE HINTS =====")
    for p, cats, text in candidates:
        if not str(p).startswith("frontend/src"):
            continue
        if "hilega" not in cats and "midpoint" not in cats:
            continue
        for m in re.finditer(
            r"(?:function|const|export\s+default\s+function|type|interface)\s+([A-Za-z0-9_]*(?:Hilega|Milega|Midpoint|Audit|Replay)[A-Za-z0-9_]*)",
            text,
            re.I,
        ):
            line = text[:m.start()].count("\n") + 1
            print(f"{p}:{line}: {m.group(0)[:180]}")

    print("\n===== BACKEND API HINTS =====")
    for p, cats, text in candidates:
        if not str(p).startswith("backend"):
            continue
        if not ({"hilega", "midpoint"} & set(cats)):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if (
                "/api/" in low
                or "@app.get" in low
                or "@router.get" in low
                or "historical" in low
                or "replay" in low
            ):
                if "hilega" in low or "midpoint" in low or "historical" in low or "replay" in low:
                    print(f"{p}:{i}: {line[:240]}")

    print("\n===== RECOMMENDED NEXT INPUT =====")
    print("Paste this full output. The next patch will reuse existing Hilega components/routes instead of duplicating UI.")
    print("No restart is required for this pre-flight.")

if __name__ == "__main__":
    main()
