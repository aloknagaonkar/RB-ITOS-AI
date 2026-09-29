import {useEffect,useMemo,useState} from 'react'
import './liveShadow.css'
import './midpointStrategyShadow.css'

type AuditCheck={name:string;result:'PASS'|'FAIL'|'INFO';observed:string;required:string;why?:string;gap?:string}
type AuditUi={
 market:{nifty:number|null;reference_type:string|null;reference_high:number|null;reference_low:number|null;midpoint:number|null;boundary:number|null;directional_points:number|null};
 vwap:{futures_close:number|null;futures_vwap:number|null;raw_diff:number|null;directional_value:number|null;position:string};
 strategy:{owner:string|null;direction:string|null;event_type:string;result:string|null;reason:string|null};
 option:{intent:string|null;exact_contract_available:boolean;expiry:string|null;strike:number|null;instrument_key:string|null;entry_premium:number|null;exit_premium:number|null;note:string};
 checks:{structure:AuditCheck[];strategy:AuditCheck[];management:AuditCheck[]}
}
type AuditEvent={event_id:string;session_date:string;strategy:string;version:string;family:string|null;event_timestamp:string;event_type:string;direction:string|null;state_before:string|null;state_after:string|null;result:string|null;reason:string|null;underlying_price:number|null;directional_points:number|null;reference_type:string|null;reference_high:number|null;reference_low:number|null;midpoint:number|null;original_boundary:number|null;futures_price:number|null;futures_vwap:number|null;directional_vwap_value:number|null;evidence:Record<string,any>;ui?:AuditUi;observation_only:boolean;execution_enabled:boolean;paper_order_enabled:boolean;quantity:null}
type WorkspaceStatus={workspace:string;display_name:string;version:string;mode:string;families:Record<string,{enabled:boolean}>;management:Record<string,any>;safety:{observation_only:boolean;execution_enabled:boolean;paper_order_enabled:boolean;quantity:null}}
type Status={model:string;mode?:string;workspace:WorkspaceStatus;audit_record_count:number;session_dates?:string[];event_counts:Record<string,number>;family_b_state:string;latest_event:AuditEvent|null;latest_entry:AuditEvent|null;latest_plus20:AuditEvent|null;latest_classifier:AuditEvent|null;latest_degraded:AuditEvent|null;latest_recovery:AuditEvent|null;latest_rescue:AuditEvent|null;latest_reentry:AuditEvent|null;latest_terminal?:AuditEvent|null;safety:WorkspaceStatus['safety']}
type TimelineRow={event_id:string;session_date?:string|null;timestamp:string;event_type:string;family?:string|null;display_owner?:string|null;direction:string|null;state_before:string|null;state_after:string|null;result:string|null;reason:string|null;underlying_price:number|null;directional_points:number|null;reference_type?:string|null}
type ReplayPresentation={status:string;label:string;family:string|null;direction:string|null;entry_timestamp:string|null;entry_underlying:number|null;current_underlying:number|null;directional_move:number|null;plus20:boolean;classifier:string|null;degraded:boolean;recovered:boolean;option_intent:string|null;futures_close:number|null;futures_vwap:number|null;raw_vwap_diff:number|null;vwap_position:string}
type ReplayMinute={session_date:string;timestamp:string;underlying_open:number|null;underlying_high:number|null;underlying_low:number|null;underlying_close:number|null;futures_close:number|null;futures_vwap:number|null;data_status:string;events:TimelineRow[];presentation?:ReplayPresentation|null}
type Session={session_date:string;block?:string|null;event_count?:number|null;minute_count?:number|null;first_minute?:string|null;last_minute?:string|null;source:string;status:string}
type HistResponse={session_date:string;status:Status;count:number;timeline:TimelineRow[];minute_count:number;minutes:ReplayMinute[]}

const base='/api/live-shadow/midpoint-strategy'
const get=async<T,>(path:string):Promise<T>=>{const r=await fetch(base+path);if(!r.ok){const e=await r.json().catch(()=>null);throw new Error(e?.detail||'Midpoint Strategy request failed')}return r.json()}
const words=(v:any)=>v==null?'—':String(v).replaceAll('_',' ')
const num=(v:any,d=2)=>v==null?'—':Number(v).toLocaleString('en-IN',{maximumFractionDigits:d})
const dt=(v:string|null|undefined)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'
const tm=(v:string|null|undefined)=>v?new Date(v).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'
const yn=(v:any)=>v?'YES':'NO'
const eventClass=(v:string)=>{const x=String(v||'').toUpperCase();if(x.includes('ENTRY'))return'mp-entry';if(x==='PLUS20_PROOF'||x.includes('RUNNER_STRENGTHENING'))return'mp-positive';if(x.includes('DEGRADED'))return'mp-warning';if(x.includes('CAP20'))return'mp-rescue';if(x.includes('STRUCTURAL_TERMINAL')||x.includes('INVALIDATED')||x.includes('EXPIRED'))return'mp-terminal';if(x.includes('BOUNDARY'))return'mp-boundary';if(x.includes('MIDPOINT'))return'mp-midpoint';return'mp-neutral'}
const semanticOwner=(event:{event_type?:string|null;reason?:string|null;family?:string|null;display_owner?:string|null}|null|undefined)=>{if(!event)return'—';if(event.display_owner)return event.display_owner;const et=String(event.event_type??'').toUpperCase();const reason=String(event.reason??'').toUpperCase();const family=String(event.family??'').toUpperCase();if(et==='BOUNDARY_OWNER_OTHER'&&reason==='FRESH_CANDIDATE_A_AT_BOUNDARY')return'FRESH A';if(family==='OTHER_FRESH_A')return'FRESH A';return words(event.family)}

function EventCard({label,event}:{label:string;event:AuditEvent|null|undefined}){return <article className={`mp-card ${eventClass(event?.event_type??'')}`}><span>{label}</span><b>{event?words(event.result||event.event_type):'—'}</b><small>{event?`${tm(event.event_timestamp)} · ${words(event.reason)}`:'No event yet'}</small></article>}

function CheckTable({title,rows}:{title:string;rows:AuditCheck[]|undefined}){
 if(!rows?.length)return null
 return <section className="mp-check-section"><div className="mp-section-title">{title}</div><div className="mp-check-scroll"><table className="mp-check-table"><thead><tr><th>Check</th><th>Result</th><th>Observed</th><th>Required / what qualifies</th><th>Why / gap</th></tr></thead><tbody>{rows.map((r,i)=><tr key={`${r.name}-${i}`}><td><b>{r.name}</b></td><td><span className={`mp-check-result ${r.result.toLowerCase()}`}>{r.result}</span></td><td>{r.observed||'—'}</td><td>{r.required||'—'}</td><td>{r.why||r.gap||'—'}{r.why&&r.gap?<><br/><small>{r.gap}</small></>:null}</td></tr>)}</tbody></table></div></section>
}

function AuditDetail({event}:{event:AuditEvent}){
 const ui=event.ui
 return <div className="hilega-audit-body mp-audit-detail">
  <div className="mp-audit-summary">
   <article><span>Event</span><b>{words(event.event_type)}</b><small>{dt(event.event_timestamp)}</small></article>
   <article><span>Owner / family</span><b>{semanticOwner(event)}</b><small>{words(event.direction)}</small></article>
   <article><span>Result</span><b>{words(event.result)}</b><small>{words(event.reason)}</small></article>
   <article><span>Option intent</span><b>{ui?.option.intent??(event.direction==='BULLISH'?'BUY CE':event.direction==='BEARISH'?'BUY PE':'—')}</b><small>{ui?.option.exact_contract_available?'Exact contract available':'Intent only · exact contract not selected'}</small></article>
  </div>

  <div className="mp-evidence-grid">
   <section className="mp-evidence-card"><div className="mp-section-title">NIFTY / STRUCTURE</div><div className="mp-kv"><span>NIFTY</span><b>{num(ui?.market.nifty??event.underlying_price)}</b><span>Reference</span><b>{words(ui?.market.reference_type??event.reference_type)}</b><span>High</span><b>{num(ui?.market.reference_high??event.reference_high)}</b><span>Low</span><b>{num(ui?.market.reference_low??event.reference_low)}</b><span>Midpoint</span><b>{num(ui?.market.midpoint??event.midpoint)}</b><span>Boundary</span><b>{num(ui?.market.boundary??event.original_boundary)}</b><span>Directional move</span><b>{num(ui?.market.directional_points??event.directional_points)}</b></div></section>

   <section className="mp-evidence-card"><div className="mp-section-title">FUTURES / VWAP</div><div className="mp-kv"><span>Futures close</span><b>{num(ui?.vwap.futures_close??event.futures_price)}</b><span>Futures VWAP</span><b>{num(ui?.vwap.futures_vwap??event.futures_vwap)}</b><span>Raw futures − VWAP</span><b>{num(ui?.vwap.raw_diff)}</b><span>VWAP position</span><b className={ui?.vwap.position==='BELOW VWAP'?'mp-bear':ui?.vwap.position==='ABOVE VWAP'?'mp-bull':''}>{ui?.vwap.position??'—'}</b><span>Directional VWAP</span><b>{num(ui?.vwap.directional_value??event.directional_vwap_value)}</b></div></section>

   <section className="mp-evidence-card"><div className="mp-section-title">STRATEGY DECISION</div><div className="mp-kv"><span>Owner</span><b>{ui?.strategy.owner??semanticOwner(event)}</b><span>Direction</span><b>{words(ui?.strategy.direction??event.direction)}</b><span>Event</span><b>{words(ui?.strategy.event_type??event.event_type)}</b><span>Result</span><b>{words(ui?.strategy.result??event.result)}</b><span>Reason</span><b>{words(ui?.strategy.reason??event.reason)}</b></div></section>

   <section className="mp-evidence-card"><div className="mp-section-title">OPTION</div><div className="mp-kv"><span>Intent</span><b>{ui?.option.intent??'—'}</b><span>Expiry</span><b>{ui?.option.expiry??'Not selected'}</b><span>Strike</span><b>{ui?.option.strike??'Not selected'}</b><span>Instrument</span><b>{ui?.option.instrument_key??'Not selected'}</b><span>Entry premium</span><b>{num(ui?.option.entry_premium)}</b><span>Exit premium</span><b>{num(ui?.option.exit_premium)}</b></div><p className="mp-option-note">{ui?.option.note??'Exact option evidence is not available in the current Midpoint audit.'}</p></section>
  </div>

  <CheckTable title="STRUCTURE QUALIFICATION" rows={ui?.checks.structure}/>
  <CheckTable title="STRATEGY / OWNERSHIP QUALIFICATION" rows={ui?.checks.strategy}/>
  <CheckTable title="MANAGEMENT QUALIFICATION" rows={ui?.checks.management}/>

  <details className="mp-raw-details"><summary>Decision evidence · raw</summary><pre>{JSON.stringify(event.evidence??{},null,2)}</pre></details>
  <details className="mp-raw-details"><summary>Raw immutable audit event</summary><pre>{JSON.stringify(event,null,2)}</pre></details>
 </div>
}

function LiveAuditTable({timeline,onInspect,selected}:{timeline:TimelineRow[];onInspect:(id:string)=>void;selected:AuditEvent|null}){return <section className="panel shadow-panel"><div className="panel-heading"><div><h2>Midpoint candle-by-candle decision audit</h2><p>Latest two available live sessions. Inspect shows the same qualification detail used by historical replay.</p></div><span className="pill teal">LIVE</span></div><div className="shadow-table-scroll mp-table-scroll"><table className="shadow-table mp-table"><thead><tr><th>Time</th><th>Session</th><th>Event</th><th>Owner</th><th>Direction</th><th>State</th><th>Result</th><th>Reason</th><th>NIFTY</th><th>Points</th><th>Audit</th></tr></thead><tbody>{[...timeline].reverse().flatMap(x=>{const expanded=selected?.event_id===x.event_id;return [<tr key={x.event_id} className={eventClass(x.event_type)}><td>{tm(x.timestamp)}</td><td>{x.session_date??'—'}</td><td><b>{words(x.event_type)}</b></td><td>{semanticOwner(x)}</td><td>{words(x.direction)}</td><td>{words(x.state_after||x.state_before)}</td><td>{words(x.result)}</td><td className="mp-reason">{words(x.reason)}</td><td>{num(x.underlying_price)}</td><td>{num(x.directional_points)}</td><td><button className="secondary" aria-expanded={expanded} onClick={()=>onInspect(x.event_id)}>{expanded?'Collapse':'Inspect'}</button></td></tr>,expanded&&selected?<tr key={x.event_id+'-detail'} className="mp-inline-detail-row"><td colSpan={11}><div className="mp-inline-audit"><div className="mp-inline-audit-head"><div><span>DETAILED AUDIT</span><b>{words(selected.event_type)}</b><small>{dt(selected.event_timestamp)}</small></div><button className="secondary" onClick={()=>onInspect(x.event_id)}>Collapse</button></div><AuditDetail event={selected}/></div></td></tr>:null]})}{!timeline.length&&<tr><td colSpan={11} className="empty">No Midpoint audit evidence for this view.</td></tr>}</tbody></table></div></section>}

function ContinuationCard({p}:{p:ReplayPresentation}){
 return <div className={`mp-continuation ${p.status==='EXIT'?'exit':''}`}>
  <div><b>{p.label}</b><small>{words(p.family)} · {words(p.direction)} · {p.option_intent??'—'}</small></div>
  <div className="mp-continuation-metrics"><span>Move <b>{num(p.directional_move)}</b></span><span>VWAP <b>{p.vwap_position}</b></span><span>Raw diff <b>{num(p.raw_vwap_diff)}</b></span><span>+20 <b>{p.plus20?'YES':'NO'}</b></span><span>Classifier <b>{words(p.classifier)}</b></span><span>Degraded <b>{p.degraded?'YES':'NO'}</b></span></div>
 </div>
}

function ReplayMinuteTable({minutes,onInspect,selected}:{minutes:ReplayMinute[];onInspect:(id:string)=>void;selected:AuditEvent|null}){return <section className="panel shadow-panel"><div className="panel-heading"><div><h2>Full-day minute replay</h2><p>Every minute remains evidence-faithful. Active continuation is a UI projection only; immutable audit events are unchanged.</p></div><span className="pill teal">REPLAY</span></div><div className="shadow-table-scroll mp-minute-scroll"><table className="shadow-table mp-minute-table"><thead><tr><th>Time</th><th>NIFTY O</th><th>H</th><th>L</th><th>C</th><th>Fut close</th><th>Fut VWAP</th><th>Data</th><th>Strategy / continuation / audit</th></tr></thead><tbody>{minutes.flatMap(m=>{const first=m.events?.[0];const expanded=!!selected&&!!m.events?.some(e=>e.event_id===selected.event_id);return [<tr key={m.timestamp} className={first?eventClass(first.event_type):m.presentation?'mp-minute-active':'mp-minute-plain'}><td><b>{tm(m.timestamp)}</b></td><td>{num(m.underlying_open)}</td><td>{num(m.underlying_high)}</td><td>{num(m.underlying_low)}</td><td>{num(m.underlying_close)}</td><td>{num(m.futures_close)}</td><td>{num(m.futures_vwap)}</td><td><span className={'mp-data-status '+(m.data_status!=='BOTH'?'warn':'')}>{words(m.data_status)}</span></td><td>{m.presentation&&<ContinuationCard p={m.presentation}/>} {m.events?.length?<div className="mp-minute-events">{m.events.map(e=><div className="mp-minute-event" key={e.event_id}><div><b>{words(e.event_type)}</b><small>{semanticOwner(e)} · {words(e.direction)} · {words(e.result)}</small><small>{words(e.reason)}</small></div><button className="secondary" aria-expanded={selected?.event_id===e.event_id} onClick={()=>onInspect(e.event_id)}>{selected?.event_id===e.event_id?'Collapse':'Inspect'}</button></div>)}</div>:!m.presentation?<span className="mp-no-event">—</span>:null}</td></tr>,expanded&&selected?<tr key={m.timestamp+'-detail'} className="mp-inline-detail-row"><td colSpan={9}><div className="mp-inline-audit"><div className="mp-inline-audit-head"><div><span>DETAILED AUDIT</span><b>{words(selected.event_type)}</b><small>{dt(selected.event_timestamp)}</small></div><button className="secondary" onClick={()=>onInspect(selected.event_id)}>Collapse</button></div><AuditDetail event={selected}/></div></td></tr>:null]})}{!minutes.length&&<tr><td colSpan={9} className="empty">No full-day minute evidence materialized for this date.</td></tr>}</tbody></table></div></section>}

function SessionView({mode,status,timeline,minutes,selected,onInspect}:{mode:'LIVE'|'HISTORICAL_REPLAY';status:Status|null;timeline:TimelineRow[];minutes:ReplayMinute[];selected:AuditEvent|null;onInspect:(id:string)=>void}){
 const current=status?.latest_event
 return <><div className="shadow-safety"><b>MIDPOINT STRATEGY · {mode==='LIVE'?'OBSERVATION ONLY':'HISTORICAL REPLAY'}</b><span>Execution disabled</span><span>Paper orders disabled</span><span>Quantity none</span><span>{mode==='LIVE'?'Current + previous available trading session':'One selected trading date'}</span></div>
 <div className="shadow-metrics mp-summary"><article><span>Owner</span><b>{semanticOwner(current??status?.latest_entry)}</b><small>FRESH A = fresh Candidate A owns boundary; not B/E</small></article><article><span>Direction</span><b>{words(current?.direction)}</b><small>{words(current?.reference_type)} reference</small></article><article><span>Family state</span><b>{words(status?.family_b_state)}</b><small>{status?.audit_record_count??0} strategy events</small></article><article><span>Latest event</span><b>{words(current?.event_type)}</b><small>{tm(current?.event_timestamp)}</small></article><article><span>Boundary / midpoint</span><b>{num(current?.original_boundary)} / {num(current?.midpoint)}</b><small>High {num(current?.reference_high)} · Low {num(current?.reference_low)}</small></article><article><span>Safety</span><b>{status?.safety.observation_only?'SAFE':'CHECK'}</b><small>Execution {status?.safety.execution_enabled?'ON':'OFF'} · Paper {status?.safety.paper_order_enabled?'ON':'OFF'}</small></article></div>
 <div className="mp-lifecycle-grid"><EventCard label="Entry" event={status?.latest_entry}/><EventCard label="+20 proof" event={status?.latest_plus20}/><EventCard label="Runner classification" event={status?.latest_classifier}/><EventCard label="Degraded" event={status?.latest_degraded}/><EventCard label="CAP20 rescue" event={status?.latest_rescue}/><EventCard label="Structural terminal" event={status?.latest_terminal}/></div>
 {mode==='HISTORICAL_REPLAY'?<ReplayMinuteTable minutes={minutes} onInspect={onInspect} selected={selected}/>:<LiveAuditTable timeline={timeline} onInspect={onInspect} selected={selected}/>}</>
}

export default function MidpointStrategyShadow(){
 const [mode,setMode]=useState<'LIVE'|'HISTORICAL_REPLAY'>('LIVE')
 const [status,setStatus]=useState<Status|null>(null)
 const [timeline,setTimeline]=useState<TimelineRow[]>([])
 const [minutes,setMinutes]=useState<ReplayMinute[]>([])
 const [sessions,setSessions]=useState<Session[]>([])
 const [selectedDate,setSelectedDate]=useState('')
 const [selected,setSelected]=useState<AuditEvent|null>(null)
 const [error,setError]=useState('')
 const [loading,setLoading]=useState(true)

 const refreshLive=async()=>{try{const [s,t]=await Promise.all([get<Status>('/status'),get<{timeline:TimelineRow[]}>('/timeline?limit=200')]);setStatus(s);setTimeline(t.timeline);setMinutes([]);setError('')}catch(e){setError((e as Error).message)}finally{setLoading(false)}}
 const fetchReplay=async(date:string)=>{if(!date)return;setLoading(true);setSelected(null);try{const r=await get<HistResponse>('/historical/session?session_date='+encodeURIComponent(date));setSelectedDate(date);setStatus(r.status);setTimeline(r.timeline);setMinutes(r.minutes??[]);setError('')}catch(e){setError((e as Error).message)}finally{setLoading(false)}}

 useEffect(()=>{if(mode!=='LIVE')return;let active=true;const poll=()=>{if(active)void refreshLive()};poll();const id=window.setInterval(poll,5000);return()=>{active=false;window.clearInterval(id)}},[mode])
 useEffect(()=>{if(mode!=='HISTORICAL_REPLAY')return;let active=true;setLoading(true);void (async()=>{try{const r=await get<{sessions:Session[]}>('/historical/sessions');if(!active)return;const available=r.sessions??[];setSessions(available);const date=available.some(x=>x.session_date===selectedDate)?selectedDate:(available[0]?.session_date??'');setSelectedDate(date);if(date){const replay=await get<HistResponse>('/historical/session?session_date='+encodeURIComponent(date));if(!active)return;setStatus(replay.status);setTimeline(replay.timeline);setMinutes(replay.minutes??[]);setError('')}else{setStatus(null);setTimeline([]);setMinutes([])}}catch(e){if(active)setError((e as Error).message)}finally{if(active)setLoading(false)}})();return()=>{active=false}},[mode])

 const inspect=async(eventId:string)=>{if(selected?.event_id===eventId){setSelected(null);return}try{const path=mode==='LIVE'?'/audit-detail?event_id='+encodeURIComponent(eventId):'/historical/audit-detail?session_date='+encodeURIComponent(selectedDate)+'&event_id='+encodeURIComponent(eventId);const r=await get<{event:AuditEvent}>(path);setSelected(r.event);setError('')}catch(e){setError((e as Error).message)}}
 const latestSessions=useMemo(()=>status?.session_dates??[],[status])
 const orderedDates=useMemo(()=>sessions.map(x=>x.session_date).sort(),[sessions])
 const selectedIndex=orderedDates.indexOf(selectedDate)
 const previousDate=selectedIndex>0?orderedDates[selectedIndex-1]:''
 const nextDate=selectedIndex>=0&&selectedIndex<orderedDates.length-1?orderedDates[selectedIndex+1]:''
 const selectedSession=sessions.find(x=>x.session_date===selectedDate)
 const replaySource=selectedSession?.source==='FORWARD_OOS_REPLAY'?'FORWARD OOS REPLAY · NO-REENTRY BASELINE':selectedSession?.source==='V57_PARITY_PROVEN_REPLAY'?'V57 PARITY-PROVEN REPLAY':words(selectedSession?.source)

 return <div className="shadow-page hilega-page midpoint-page">{error&&<div role="alert" className="banner error">{error}</div>}<div className="mp-modebar"><div><button className={mode==='LIVE'?'primary':'secondary'} onClick={()=>{setMode('LIVE');setSelected(null);setLoading(true)}}>Live shadow</button><button className={mode==='HISTORICAL_REPLAY'?'primary':'secondary'} onClick={()=>{setMode('HISTORICAL_REPLAY');setSelected(null);setLoading(true)}}>Historical replay</button></div>{mode==='LIVE'?<small>Visible sessions: {latestSessions.length?latestSessions.join(' + '):'waiting for audit'}</small>:<div className="mp-replay-controls"><button className="secondary" disabled={!previousDate||loading} onClick={()=>void fetchReplay(previousDate)}>← Previous date</button><select value={selectedDate} disabled={loading&&!sessions.length} onChange={e=>void fetchReplay(e.target.value)}>{!sessions.length&&<option value="">No materialized sessions</option>}{sessions.map(x=><option key={x.session_date} value={x.session_date}>{x.session_date} · {x.minute_count??0} min · {x.event_count??0} events</option>)}</select><button className="secondary" disabled={!nextDate||loading} onClick={()=>void fetchReplay(nextDate)}>Next date →</button><button className="primary" disabled={!selectedDate||loading} onClick={()=>void fetchReplay(selectedDate)}>{loading?'Loading…':'Reload date'}</button></div>}</div>{mode==='HISTORICAL_REPLAY'&&selectedDate&&<div className="mp-replay-banner"><b>HISTORICAL REPLAY</b><span>{selectedDate}</span><span>{minutes.length} minute rows</span><span>{timeline.length} strategy events</span><small>{selectedSession?.block??'tested source'} · {replaySource} · manual validation · no broker / no execution</small></div>}{loading&&!status?<section className="panel"><div className="empty">Loading Midpoint Strategy…</div></section>:<SessionView mode={mode} status={status} timeline={timeline} minutes={minutes} selected={selected} onInspect={id=>void inspect(id)}/>}</div>
}
