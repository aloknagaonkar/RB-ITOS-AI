from pathlib import Path

API = Path("backend/market_lab/historical_replay_operations_api_v1.py")
OPS = Path("frontend/src/historicalReplayOperations.tsx")
REPLAY = Path("frontend/src/historicalReplay.tsx")

API.write_text(Path("backend/market_lab/historical_replay_operations_api_v1_1.py").read_text(encoding="utf-8"), encoding="utf-8")
OPS.write_text(Path("frontend/src/historicalReplayOperations.v1_1.tsx").read_text(encoding="utf-8"), encoding="utf-8")

text = REPLAY.read_text(encoding="utf-8")

old_selector = "\n".join([
'      <label>Date',
'        <select value={selected} onChange={e=>setSelected(e.target.value)}>',
'          {!sessions.length&&<option value="">No replay sessions</option>}',
'          {sessions.map(s=><option key={s.session_date} value={s.session_date}>{s.session_date}</option>)}',
'        </select>',
'      </label>',
])
new_selector = "\n".join([
'      <label>Date',
'        <input',
'          type="date"',
'          value={selected}',
'          list="historical-replay-session-dates"',
'          onChange={e=>setSelected(e.target.value)}',
'        />',
'        <datalist id="historical-replay-session-dates">',
'          {sessions.map(s=><option key={s.session_date} value={s.session_date}/>)}',
'        </datalist>',
'      </label>',
])
if old_selector not in text:
    raise SystemExit("Safe-stop: Historical Replay date selector block not found.")
text = text.replace(old_selector, new_selector, 1)

old_fetch = "\n".join([
'    Promise.all([',
'      fetch(`/api/live-shadow/replay/status?date=${encodeURIComponent(selected)}`).then(r=>{if(!r.ok) throw new Error(\'Replay status unavailable\');return r.json()}),',
'      fetch(`/api/live-shadow/replay/timeline?date=${encodeURIComponent(selected)}`).then(r=>{if(!r.ok) throw new Error(\'Replay timeline unavailable\');return r.json()}),',
'    ]).then(([s,t])=>{',
'      if(!active)return',
'      setStatus(s.status||null)',
'      setTimeline(t.rows||[])',
'    }).catch(e=>{if(active)setError(String(e))})',
'      .finally(()=>{if(active)setLoading(false)})',
])
new_fetch = "\n".join([
'    const optionalJson=async(url:string)=>{',
'      const r=await fetch(url)',
'      if(r.status===404) return null',
'      if(!r.ok) throw new Error(\'Replay data unavailable\')',
'      return r.json()',
'    }',
'    Promise.all([',
'      optionalJson(`/api/live-shadow/replay/status?date=${encodeURIComponent(selected)}`),',
'      optionalJson(`/api/live-shadow/replay/timeline?date=${encodeURIComponent(selected)}`),',
'    ]).then(([s,t])=>{',
'      if(!active)return',
'      setStatus(s?.status||null)',
'      setTimeline(t?.rows||[])',
'    }).catch(e=>{if(active)setError(String(e))})',
'      .finally(()=>{if(active)setLoading(false)})',
])
if old_fetch not in text:
    raise SystemExit("Safe-stop: Historical Replay fetch block not found.")
text = text.replace(old_fetch, new_fetch, 1)

REPLAY.write_text(text, encoding="utf-8")
print("Historical Replay hardening V1.1 applied.")
