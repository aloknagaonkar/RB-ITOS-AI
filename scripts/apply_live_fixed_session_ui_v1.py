"""Apply read-only fixed-session UI projection wiring."""
from pathlib import Path
import re, shutil

API=Path("backend/market_lab/api.py")
APP=Path("frontend/src/App.tsx")
API_BAK=Path(str(API)+".pre-fixed-session-ui-v1")
APP_BAK=Path(str(APP)+".pre-fixed-session-ui-v1")
IMPORT="from .live_fixed_session_ui_projection_v1 import attach_fixed_session_trends, load_fixed_anchor_index, project_fixed_session_ui\n"

def backup(src,dst):
    if not dst.exists():
        shutil.copy2(src,dst); print("Backup:",dst)

def once(text,old,new,label):
    if new in text:return text
    count=text.count(old)
    if count!=1:raise SystemExit(f"ABORT {label}: expected 1 match, found {count}")
    return text.replace(old,new,1)

if not API.exists():raise SystemExit("ABORT missing backend/market_lab/api.py")
api=API.read_text(encoding="utf-8"); backup(API,API_BAK)
if IMPORT.strip() not in api:
    marker="def create_app(engine=None, historical_gateway_factory=None):"
    if marker not in api:raise SystemExit("ABORT api create_app marker missing")
    api=api.replace(marker,IMPORT+"\n"+marker,1)

api=once(api,
'''            count = session.scalar(
                select(func.count()).select_from(Observation).where(Observation.config_id == config_id)
            )
            history = []
''',
'''            count = session.scalar(
                select(func.count()).select_from(Observation).where(Observation.config_id == config_id)
            )
            fixed_anchor_index = load_fixed_anchor_index()
            history = []
''',"api state anchor index")

api=once(api,
'''                        "range_changed": previous_signature is not None and signature != previous_signature,
''',
'''                        "range_changed": previous_signature is not None and signature != previous_signature,
                        "fixed_session_ui": project_fixed_session_ui(
                            row.snapshot,
                            row.evaluation,
                            anchor_index=fixed_anchor_index,
                        ),
''',"api history projection")

api=once(api,
'''                previous_signature = signature
            latest = rows[0] if rows else None
''',
'''                previous_signature = signature
            attach_fixed_session_trends(
                history,
                tolerance_seconds=config.trend_timestamp_tolerance_seconds,
                flat_threshold=config.trend_flat_threshold,
            )
            latest = rows[0] if rows else None
''',"api fixed trends")

start=api.find('    @app.get("/api/observations/{observation_id}")')
end=api.find("\n    @app.",start+10)
if start<0:raise SystemExit("ABORT observation endpoint missing")
if end<0:end=len(api)
block=api[start:end]
block=once(block,
'''                "evaluation": row.evaluation,
            }
''',
'''                "evaluation": row.evaluation,
                "fixed_session_ui": project_fixed_session_ui(
                    row.snapshot,
                    row.evaluation,
                ),
            }
''',"observation detail projection")
api=api[:start]+block+api[end:]
API.write_text(api,encoding="utf-8"); print("Patched:",API)

if not APP.exists():raise SystemExit("ABORT missing frontend/src/App.tsx")
app=APP.read_text(encoding="utf-8"); backup(APP,APP_BAK)
helpers=r'''
function fixedSessionUi(record:any){
  const value=record?.fixed_session_ui
  return value?.status==='AVAILABLE' ? value : null
}
function displayFixedResult(record:any,result:any){
  return fixedSessionUi(record)?.display_result ?? result
}
function displayAnchorStatus(detail:any){
  const value=fixedSessionUi(detail)
  if(!value) return words(detail?.evaluation?.anchor_status)
  return value.provenance==='ANCHOR_LIVE' ? 'live' : 'recovered'
}
function fixedSessionTrend(record:any,horizon:number,existing:any){
  return record?.fixed_session_trends?.[String(horizon)] ?? existing
}
function FixedSessionOISection({detail}:{detail:any}){
  const value=fixedSessionUi(detail)
  if(!value) return null
  const result=value.display_result
  const pct=(v:number|null|undefined)=>v==null?'—':`${signed(v,2)}%`
  return <section className="oi-section fixed">
    <div className="oi-heading">
      <div>
        <h2>Fixed morning ATM</h2>
        <p>ATM {number(value.atm)} / {value.strikes.length} strikes / {result.received}/{result.expected} contracts · {value.label}</p>
      </div>
      <strong>{value.current_pcr==null?'—':Number(value.current_pcr).toFixed(3)} <small>PCR</small></strong>
    </div>
    <div className="table-scroll"><table>
      <thead><tr><th>Strike</th><th>Call OI</th><th>Call ΔOI</th><th>Call Δ%</th><th>Put OI</th><th>Put ΔOI</th><th>Put Δ%</th><th>Strike PCR</th></tr></thead>
      <tbody>{value.rows.map((row:any)=><tr key={row.strike}>
        <td>{number(row.strike)}</td><td>{number(row.call_oi)}</td><td>{signed(row.call_change_oi)}</td><td>{pct(row.call_change_pct)}</td>
        <td>{number(row.put_oi)}</td><td>{signed(row.put_change_oi)}</td><td>{pct(row.put_change_pct)}</td>
        <td>{row.strike_pcr==null?'—':Number(row.strike_pcr).toFixed(3)}</td>
      </tr>)}</tbody>
      <tfoot><tr><th>Total</th><th>{number(value.current_ce_oi)}</th><th>{signed(value.ce_delta)}</th><th>{pct(result.call_change_pct)}</th>
        <th>{number(value.current_pe_oi)}</th><th>{signed(value.pe_delta)}</th><th>{pct(result.put_change_pct)}</th>
        <th>{value.current_pcr==null?'—':Number(value.current_pcr).toFixed(3)}</th></tr></tfoot>
    </table></div>
    <p className="oi-issue">{value.label}
      {value.source_candle_time ? ` · source ${new Date(value.source_candle_time).toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:false})} completed 1m` : ''}
    </p>
  </section>
}

'''
if "function fixedSessionUi(record:any)" not in app:
    m=re.search(r"(?m)^function OISection\(",app)
    if not m:raise SystemExit("ABORT frontend OISection marker missing")
    app=app[:m.start()]+helpers+app[m.start():]

app=once(app,
"          const result = pcrLatest?.evaluation.results.find(r=>r.mode===mode)\n",
"""          const rawResult = pcrLatest?.evaluation.results.find(r=>r.mode===mode)
          const result = mode==='fixed' ? displayFixedResult(pcrLatest,rawResult) : rawResult
""","frontend summary result")

pattern=re.compile(r'(?m)^(\s*)const\s+(\w+)\s*=\s*\(seconds:number\)\s*=>\s*trends\.find\(t=>t\.mode===mode&&t\.requested_horizon_seconds===seconds\)\s*$')
m=pattern.search(app)
if m:
    indent,name=m.group(1),m.group(2)
    repl=(f"{indent}const {name} = (seconds:number)=>{{\n"
          f"{indent}  const existing=trends.find(t=>t.mode===mode&&t.requested_horizon_seconds===seconds)\n"
          f"{indent}  return mode==='fixed' ? fixedSessionTrend(pcrLatest,seconds,existing) : existing\n"
          f"{indent}}}")
    app=app[:m.start()]+repl+app[m.end():]
else:
    print("NOTE: exact summary trend helper not found; summary PCR/ATM still patched.")

app=once(app,
'<div className="oi-sections">{detail.evaluation.results.map(result=><OISection key={result.mode} detail={detail} result={result}/>)}</div>',
'''<div className="oi-sections">{detail.evaluation.results.map(result=>
              result.mode==='fixed' && fixedSessionUi(detail)
                ? <FixedSessionOISection key={result.mode} detail={detail}/>
                : <OISection key={result.mode} detail={detail} result={result}/>
            )}</div>''',"frontend inspector section")

if "displayAnchorStatus(detail)" not in app:
    if "words(detail.evaluation.anchor_status)" in app:
        app=app.replace("words(detail.evaluation.anchor_status)","displayAnchorStatus(detail)",1)
    elif "detail.evaluation.anchor_status" in app:
        app=app.replace("detail.evaluation.anchor_status","displayAnchorStatus(detail)",1)
    else:raise SystemExit("ABORT inspector anchor status marker missing")

APP.write_text(app,encoding="utf-8"); print("Patched:",APP)
print("Read-only fixed-session UI projection wired. Stored evaluations unchanged.")
