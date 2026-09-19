from pathlib import Path

PATH = Path("frontend/src/historicalReplayOperations.tsx")
text = PATH.read_text(encoding="utf-8")

# Add top-level strict-ready state from the operations API response.
anchor = "  const [semanticRows,setSemanticRows]=useState<any[]>([])\n"
insert = "  const [strictReplayReady,setStrictReplayReady]=useState<boolean|null>(null)\n"
if "strictReplayReady" not in text:
    if anchor not in text:
        raise SystemExit("Safe-stop: semanticRows state anchor not found.")
    text = text.replace(anchor, anchor + insert, 1)

# Capture strict_replay_ready on readiness refresh.
old = """      setReadiness(value.readiness)
      setSemanticRows(value.datasets||[])
"""
new = """      setReadiness(value.readiness)
      setSemanticRows(value.datasets||[])
      setStrictReplayReady(
        typeof value.strict_replay_ready==='boolean' ? value.strict_replay_ready : null
      )
"""
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("Safe-stop: readiness assignment block not found.")

# Clear strict state when there is no session.
old_clear = """    if(!sessionDate){setReadiness(null);setSemanticRows([]);return}
"""
new_clear = """    if(!sessionDate){setReadiness(null);setSemanticRows([]);setStrictReplayReady(null);return}
"""
if old_clear in text:
    text = text.replace(old_clear, new_clear, 1)

# Replace legacy checkpoint-ready derivation with strict API value when present.
old_ready = """  const checkpointReady=Boolean(
    readiness?.checkpoint_replay_ready ??
    readiness?.checkpoint_ready ??
    readiness?.full_replay_prerequisites_ready ??
    readiness?.full_trade_replay_prerequisites_ready
  )
"""
new_ready = """  const checkpointReady = strictReplayReady!==null
    ? strictReplayReady
    : Boolean(
        readiness?.checkpoint_replay_ready ??
        readiness?.checkpoint_ready ??
        readiness?.full_replay_prerequisites_ready ??
        readiness?.full_trade_replay_prerequisites_ready
      )
"""
if old_ready in text:
    text = text.replace(old_ready, new_ready, 1)
elif new_ready not in text:
    raise SystemExit("Safe-stop: checkpointReady block not found.")

PATH.write_text(text, encoding="utf-8")
print("Applied Historical Replay UI strict-ready gating fix V1.")
