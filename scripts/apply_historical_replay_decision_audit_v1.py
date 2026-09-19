from pathlib import Path

UI = Path("frontend/src/historicalReplay.tsx")
CSS = Path("frontend/src/historicalReplay.css")
if not UI.exists():
    raise SystemExit("Safe-stop: frontend/src/historicalReplay.tsx not found.")

text = UI.read_text(encoding="utf-8")

component = r"""
type DecisionGate={
  id:string
  stage:string
  required:boolean
  result:'PASS'|'FAIL'|'INFO'|'INCOMPLETE'|'WAIT'|'NOT_APPLICABLE'
  expected:string
  actual:string
  reason:string
}

function gateResultFromStatus(status?:string|null):DecisionGate['result']{
  const s=(status||'').toUpperCase()
  if(['PASS','ALLOWED','AVAILABLE','ALIGNED','CONFIRMED','CLASSIFIED','RESOLVED','OPEN','OPENED','DUE','ELIGIBLE'].includes(s)) return 'PASS'
  if(['FAIL','FAILED','REJECTED','MISALIGNED','BLOCKED','MISSING'].includes(s)) return 'FAIL'
  if(['INCOMPLETE','UNAVAILABLE','STALE','OUT_OF_ORDER'].includes(s)) return 'INCOMPLETE'
  return 'WAIT'
}

function progressItem(progress:ProgressItem[],...stages:string[]){
  return progress.find(x=>stages.includes(x.stage))
}

function buildDecisionGates(row:TimelineRow,progress:ProgressItem[]):DecisionGate[]{
  const f=row.normalized_features?.payload||{}
  const horizons=f.horizons||{}
  const all3=(row.all3_decision?.status||f.all3_state||'').toUpperCase()
  const candidate=(row.candidate_detection?.status||'').toUpperCase()
  const direction=all3.startsWith('BULLISH')?'BULLISH':all3.startsWith('BEARISH')?'BEARISH':null

  const health=row.data_health
  const c2Eligibility=progressItem(progress,'C2_ELIGIBILITY')
  const c2Confirmed=progressItem(progress,'CANDLE2_CONFIRMED')
  const c2Decision=progressItem(progress,'C2_DECISION')
  const futuresFetch=progressItem(progress,'FUTURES_FETCH')
  const futuresAlign=progressItem(progress,'FUTURES_ALIGNMENT_CHECKED')
  const spotClass=progressItem(progress,'SPOT_LAG_CLASSIFIED')
  const option=progressItem(progress,'OPTION_RESOLVED','OPTION_RESOLUTION')
  const entry=progressItem(progress,'ENTRY_OPENED','ENTRY_OPEN')

  const gates:DecisionGate[]=[]

  gates.push({
    id:'DATA_HEALTH',stage:'Data health',required:true,
    result:health?.status==='ALLOWED'?'PASS':health?gateResultFromStatus(health.status):'INCOMPLETE',
    expected:'Checkpoint market data must be usable.',
    actual:health?.status||'No health result',
    reason:health?.payload?.health_reason || (health?.status==='ALLOWED'?'Required market data passed the health gate.':'Required market data did not pass the health gate.'),
  })

  const h=(name:string)=>{
    const x=horizons[name]||{}
    const state=x.state||x.direction||x.result||f[`state_${name}`]||'—'
    const imbalance=x.imbalance ?? x.oi_imbalance ?? null
    const pcrChange=x.pcr_change ?? x.regular_pcr_change ?? null
    return `${state} | imbalance=${imbalance==null?'—':n(imbalance,0)} | PCR Δ=${pcrChange==null?'—':n(pcrChange,3)}`
  }

  const all3Directional=all3==='BULLISH_ALL_3'||all3==='BEARISH_ALL_3'
  gates.push({
    id:'C1_ALL3',stage:'C1 ALL3 detection',required:true,
    result:all3Directional?'PASS':'FAIL',
    expected:'5m, 10m and 15m must agree as BULLISH or BEARISH.',
    actual:`5m ${h('5m')} ; 10m ${h('10m')} ; 15m ${h('15m')} ; ALL3=${all3||'—'}`,
    reason:all3Directional?`${all3} created a directional C1 condition.`:'No directional ALL3 condition exists at this checkpoint, so no new trade can start here.',
  })

  gates.push({
    id:'NEW_CANDIDATE',stage:'New candidate',required:true,
    result:candidate==='NEW_CANDIDATE'||candidate==='DETECTED'?'PASS':all3Directional?'FAIL':'NOT_APPLICABLE',
    expected:'Directional ALL3 must represent a new opposite candidate, not just an unchanged regime.',
    actual:candidate||'—',
    reason:candidate==='NEW_CANDIDATE'||candidate==='DETECTED'
      ?'A new strategy candidate was created.'
      :all3Directional?'Directional ALL3 exists, but the checkpoint did not create a new candidate.':'No directional ALL3 exists, so candidate detection is not applicable.',
  })

  if(progress.length){
    gates.push({
      id:'C2_TIMING',stage:'C2 timing',required:true,
      result:c2Eligibility?gateResultFromStatus(c2Eligibility.display_result||c2Eligibility.status):'WAIT',
      expected:'Exact C2 checkpoint at C1 + 5 minutes.',
      actual:c2Eligibility?.detail||c2Eligibility?.status||'Waiting for C2',
      reason:c2Eligibility?.reason||'Candidate cannot advance before the exact C2 checkpoint.',
    })

    let c2Result:DecisionGate['result']='WAIT'
    let c2Actual='Waiting for C2 persistence result'
    let c2Reason='The same ALL3 direction must survive at C2.'
    if(c2Confirmed){c2Result='PASS';c2Actual=c2Confirmed.detail||c2Confirmed.status;c2Reason=c2Confirmed.reason}
    else if(c2Decision){c2Result=c2Decision.status==='CLASSIFIED'?'PASS':gateResultFromStatus(c2Decision.display_result||c2Decision.status);c2Actual=c2Decision.detail||c2Decision.status;c2Reason=c2Decision.reason}

    gates.push({
      id:'C2_PERSISTENCE',stage:'C2 persistence',required:true,result:c2Result,
      expected:`Same ${direction||'directional'} ALL3 must survive at C2.`,
      actual:c2Actual,reason:c2Reason,
    })

    gates.push({
      id:'FUTURES_DATA',stage:'Futures data',required:true,
      result:futuresFetch?gateResultFromStatus(futuresFetch.display_result||futuresFetch.status):'WAIT',
      expected:'Exact completed futures OI checkpoint must be available.',
      actual:futuresFetch?.detail||futuresFetch?.status||'Not reached',
      reason:futuresFetch?.reason||'Futures confirmation cannot run without completed futures data.',
    })

    const expectedFutures=direction==='BULLISH'?'LONG_BUILDUP or SHORT_COVERING':direction==='BEARISH'?'SHORT_BUILDUP or LONG_UNWINDING':'Directional candidate required'
    gates.push({
      id:'FUTURES_ALIGNMENT',stage:'Futures alignment',required:true,
      result:futuresAlign?gateResultFromStatus(futuresAlign.display_result||futuresAlign.status):c2Decision?.status==='REJECTED'?'FAIL':'WAIT',
      expected:expectedFutures,
      actual:futuresAlign?.detail||c2Decision?.detail||'Not reached',
      reason:futuresAlign?.reason||c2Decision?.reason||'Candidate direction must agree with the permitted futures OI states.',
    })

    gates.push({
      id:'SPOT_CLASS',stage:'Spot movement class',required:false,
      result:spotClass?'INFO':'NOT_APPLICABLE',
      expected:'Research classification only; not an entry gate.',
      actual:spotClass?.detail||'Not classified',
      reason:spotClass?.reason||'SPOT_LAG / SPOT_ALREADY_MOVED is recorded as context and does not independently permit or reject entry.',
    })

    gates.push({
      id:'OPTION_RESOLUTION',stage:'Exact ATM option',required:true,
      result:option?gateResultFromStatus(option.display_result||option.status):c2Decision?.status==='CLASSIFIED'?'WAIT':'NOT_APPLICABLE',
      expected:`Exact current ATM ${direction==='BEARISH'?'PE':direction==='BULLISH'?'CE':'option'}; no nearest-strike fallback.`,
      actual:option?.detail||option?.status||'Not reached',
      reason:option?.reason||'Entry requires an exact ATM instrument.',
    })

    gates.push({
      id:'ENTRY_OPEN',stage:'Next-minute entry',required:true,
      result:entry?'PASS':progress.some(x=>x.terminal)?'FAIL':'WAIT',
      expected:'Exact next-minute option open after all required gates pass.',
      actual:entry?.detail||entry?.status||'No entry opened',
      reason:entry?.reason||(progress.some(x=>x.terminal)?'Entry was not opened because an earlier required gate terminated the candidate.':'Waiting for all required checks and the causal next-minute entry price.'),
    })
  }

  return gates
}

function DecisionAudit({row,progress}:{row:TimelineRow,progress:ProgressItem[]}){
  const gates=buildDecisionGates(row,progress)
  const required=gates.filter(x=>x.required)
  const entry=gates.find(x=>x.id==='ENTRY_OPEN')
  const failed=required.find(x=>x.result==='FAIL'||x.result==='INCOMPLETE')
  const candidateStarted=progress.length>0 || ['NEW_CANDIDATE','DETECTED'].includes((row.candidate_detection?.status||'').toUpperCase())

  let finalTitle='NO TRADE CANDIDATE'
  let finalReason='This checkpoint did not create a new candidate.'
  let finalClass='hr-decision-neutral'
  if(entry?.result==='PASS'){finalTitle='TRADE TAKEN';finalReason='All required entry gates passed and the exact next-minute option entry was opened.';finalClass='hr-decision-pass'}
  else if(failed&&candidateStarted){finalTitle='TRADE NOT TAKEN';finalReason=`Stopped at ${failed.stage}: ${failed.reason}`;finalClass='hr-decision-fail'}
  else if(candidateStarted){finalTitle='CANDIDATE IN PROGRESS';finalReason='The candidate has not yet reached a terminal entry or rejection state.';finalClass='hr-decision-wait'}

  return <div className="hr-decision-audit">
    <div className={`hr-decision-final ${finalClass}`}><div><span>Final decision</span><b>{finalTitle}</b></div><p>{finalReason}</p></div>
    <div className="hr-decision-heading"><h4>Entry decision checks</h4><span>Required gates are evaluated independently. Context-only checks cannot reject a trade.</span></div>
    <div className="hr-decision-table-wrap"><table className="hr-decision-table">
      <thead><tr><th>Check</th><th>Role</th><th>Result</th><th>Expected</th><th>Actual evidence</th><th>Explanation</th></tr></thead>
      <tbody>{gates.map(g=><tr key={g.id} className={`hr-gate-${g.result.toLowerCase().replaceAll('_','-')}`}>
        <td><b>{g.stage}</b><code>{g.id}</code></td><td>{g.required?'REQUIRED':'CONTEXT'}</td><td>{badge(g.result)}</td><td>{g.expected}</td><td>{g.actual}</td><td>{g.reason}</td>
      </tr>)}</tbody>
    </table></div>
  </div>
}
"""

anchor = "function CheckpointDetail({row}:{row:TimelineRow}){"
if "function DecisionAudit(" not in text:
    if anchor not in text: raise SystemExit("Safe-stop: CheckpointDetail anchor not found.")
    text = text.replace(anchor, component + "\n" + anchor, 1)

render_anchor = "    <TradeSummary progress={progress}/>\n    <TerminalPanel progress={progress}/>\n"
if "<DecisionAudit row={row}" not in text:
    if render_anchor not in text: raise SystemExit("Safe-stop: summary render anchor not found.")
    text = text.replace(render_anchor, "    <DecisionAudit row={row} progress={progress}/>\n" + render_anchor, 1)

UI.write_text(text, encoding="utf-8")

css = CSS.read_text(encoding="utf-8") if CSS.exists() else ""
rules = r"""
.hr-decision-audit{margin:16px 0;border:1px solid #29404c;border-radius:12px;overflow:hidden}
.hr-decision-final{padding:14px 16px;border-bottom:1px solid #29404c}.hr-decision-final>div{display:flex;gap:12px;align-items:center}.hr-decision-final span{opacity:.68;font-size:.8rem;text-transform:uppercase}.hr-decision-final b{font-size:1.05rem}.hr-decision-final p{margin:7px 0 0;opacity:.86}
.hr-decision-pass{background:rgba(45,110,75,.12)}.hr-decision-fail{background:rgba(130,55,55,.12)}.hr-decision-wait{background:rgba(120,100,45,.10)}.hr-decision-neutral{background:rgba(70,90,105,.10)}
.hr-decision-heading{display:flex;justify-content:space-between;gap:14px;align-items:baseline;padding:12px 16px}.hr-decision-heading h4{margin:0}.hr-decision-heading span{opacity:.65;font-size:.8rem}
.hr-decision-table-wrap{overflow:auto}.hr-decision-table{width:100%;border-collapse:collapse;min-width:1050px;font-size:.82rem}.hr-decision-table th,.hr-decision-table td{padding:9px 10px;border-top:1px solid #233845;vertical-align:top;text-align:left}.hr-decision-table td:first-child b{display:block}.hr-decision-table td:first-child code{display:block;opacity:.55;margin-top:3px;font-size:.72rem}.hr-gate-fail,.hr-gate-incomplete{background:rgba(130,55,55,.07)}.hr-gate-pass{background:rgba(45,110,75,.05)}
"""
if ".hr-decision-audit" not in css:
    CSS.write_text(css.rstrip()+"\n"+rules+"\n", encoding="utf-8")

print("Applied Historical Replay Decision Audit V1.")
