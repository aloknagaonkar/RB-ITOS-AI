from pathlib import Path

PATH = Path("frontend/src/historicalReplayOperations.tsx")
text = PATH.read_text(encoding="utf-8")

# Add last-checked state.
anchor = "  const [error,setError]=useState('')\n"
insert = "  const [lastCheckedAt,setLastCheckedAt]=useState<string|null>(null)\n"
if "lastCheckedAt" not in text:
    if anchor not in text:
        raise SystemExit("Safe-stop: error state anchor not found.")
    text = text.replace(anchor, anchor + insert, 1)

# Record successful readiness completion.
needle = """      setSemanticRows(value.datasets||[])
"""
replacement = """      setSemanticRows(value.datasets||[])
      setLastCheckedAt(new Date().toLocaleTimeString())
"""
if replacement not in text:
    if needle not in text:
        raise SystemExit("Safe-stop: readiness assignment anchor not found.")
    text = text.replace(needle, replacement, 1)

# Add a persistent success/info line under the header controls.
header_anchor = """    {error&&<div className="hr-ops-error">{error}</div>}
"""
header_insert = """    {error&&<div className="hr-ops-error">{error}</div>}
    {!error&&pendingAction==='readiness'&&
      <div className="hr-ops-info">Checking readiness for {sessionDate}…</div>}
    {!error&&pendingAction!=='readiness'&&lastCheckedAt&&
      <div className="hr-ops-info">
        Readiness checked for {sessionDate} at {lastCheckedAt}.
        {checkpointReady?' Replay prerequisites are ready.':' Replay prerequisites are not ready.'}
      </div>}
"""
if "Readiness checked for {sessionDate}" not in text:
    if header_anchor not in text:
        raise SystemExit("Safe-stop: error banner anchor not found.")
    text = text.replace(header_anchor, header_insert, 1)

# Make sure changing date clears stale confirmation.
date_effect_anchor = """  useEffect(()=>{
    void refreshReadiness().catch(e=>setError(String(e)))
"""
if date_effect_anchor in text and "setLastCheckedAt(null)" not in text:
    text = text.replace(
        date_effect_anchor,
        """  useEffect(()=>{
    setLastCheckedAt(null)
    void refreshReadiness().catch(e=>setError(String(e)))
""",
        1,
    )

PATH.write_text(text, encoding="utf-8")
print("Applied visible readiness feedback V1.")
