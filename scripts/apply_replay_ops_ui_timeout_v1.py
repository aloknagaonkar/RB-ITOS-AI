from pathlib import Path

P = Path("frontend/src/historicalReplayOperations.tsx")
if not P.exists():
    raise SystemExit("Safe-stop: frontend/src/historicalReplayOperations.tsx not found")

text = P.read_text(encoding="utf-8")

old = """      const next=await requestJson(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
"""
new = """      // Replay/download launch performs a synchronous readiness check before the
      // background worker is queued. Real readiness scans can take ~14s and
      // occasionally exceed the generic 20s UI timeout. Give launch requests
      // a wider client timeout while keeping ordinary readiness/job polling at
      // the existing 20s default.
      const next=await requestJson(
        url,
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)},
        60000,
      )
"""

if old not in text:
    raise SystemExit("Safe-stop: expected replay operation requestJson call not found")

text = text.replace(old, new, 1)
P.write_text(text, encoding="utf-8")
print("Patched replay/download launch timeout to 60s; normal polling/readiness remains 20s.")
