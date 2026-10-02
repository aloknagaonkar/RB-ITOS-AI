from pathlib import Path

P = Path("frontend/src/historicalReplayOperations.tsx")
if not P.exists():
    raise SystemExit("Safe-stop: frontend/src/historicalReplayOperations.tsx not found")

text = P.read_text(encoding="utf-8")

old_readiness = """    const value=await requestJson(`/api/live-shadow/replay-ops/readiness?session_date=${encodeURIComponent(sessionDate)}`)
"""
new_readiness = """    const value=await requestJson(
      `/api/live-shadow/replay-ops/readiness?session_date=${encodeURIComponent(sessionDate)}`,
      undefined,
      60000,
    )
"""

if old_readiness in text:
    text = text.replace(old_readiness, new_readiness, 1)
elif "replay-ops/readiness" in text and "60000" in text:
    print("Readiness timeout already appears patched; leaving it unchanged.")
else:
    raise SystemExit("Safe-stop: expected readiness request block not found")

old_launch = """      const next=await requestJson(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
"""
new_launch = """      const next=await requestJson(
        url,
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)},
        60000,
      )
"""

if old_launch in text:
    text = text.replace(old_launch, new_launch, 1)
elif "const next=await requestJson(" in text and "60000" in text:
    print("Launch timeout already appears patched; leaving it unchanged.")
else:
    raise SystemExit("Safe-stop: expected run/download request block not found")

P.write_text(text, encoding="utf-8")
print("Patched replay readiness + run/download launch timeouts to 60s.")
