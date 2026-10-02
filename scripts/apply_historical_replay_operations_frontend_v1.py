from pathlib import Path
p=Path("frontend/src/historicalReplay.tsx")
text=p.read_text(encoding="utf-8")
import_line="import HistoricalReplayOperations from './historicalReplayOperations'\n"
if import_line not in text:
    lines=text.splitlines(keepends=True)
    idx=0
    for i,line in enumerate(lines):
        if line.startswith("import "):
            idx=i+1
    if idx==0: raise SystemExit("SAFE STOP: import block not found")
    lines.insert(idx,import_line)
    text="".join(lines)
old="  const [expanded,setExpanded]=useState<string|null>(null)\n"
if old in text and "refreshKey" not in text:
    text=text.replace(old, old+"  const [refreshKey,setRefreshKey]=useState(0)\n",1)
old_dep="  },[selected])"
if old_dep in text:
    text=text.replace(old_dep,"  },[selected,refreshKey])",1)
elif "[selected,refreshKey]" not in text:
    raise SystemExit("SAFE STOP: refresh dependency anchor not found")
anchor='    <div className="hr-cards">'
ops='    <HistoricalReplayOperations\n      sessionDate={selected}\n      onReplayComplete={()=>setRefreshKey(v=>v+1)}\n    />\n\n'
if anchor in text and "<HistoricalReplayOperations" not in text:
    text=text.replace(anchor,ops+anchor,1)
elif "<HistoricalReplayOperations" not in text:
    raise SystemExit("SAFE STOP: replay cards anchor not found")
p.write_text(text,encoding="utf-8")
print("Integrated Replay Operations controls into Historical Replay.")
