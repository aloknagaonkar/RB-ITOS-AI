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
type AuditEvent={event_id:string;session_date:string;strategy:string;version:string;family:string|null;event_timestamp:string;event_type:string;direction:string|null;state_before:string|null;state_after:string|null;result:string|null;reason:string|null;underlying_price:number|null;directional_points:number|null;nifty_points_from_entry?:number|null;nifty_entry_price?:number|null;reference_type:string|null;reference_high:number|null;reference_low:number|null;midpoint:number|null;original_boundary:number|null;futures_price:number|null;futures_vwap:number|null;directional_vwap_value:number|null;evidence:Record<string,any>;ui?:AuditUi;observation_only:boolean;execution_enabled:boolean;paper_order_enabled:boolean;quantity:null}
type WorkspaceStatus={workspace:string;display_name:string;version:string;mode:string;families:Record<string,{enabled:boolean}>;management:Record<string,any>;safety:{observation_only:boolean;execution_enabled:boolean;paper_order_enabled:boolean;quantity:null}}
type Status={model:string;mode?:string;workspace:WorkspaceStatus;audit_record_count:number;session_dates?:string[];event_counts:Record<string,number>;family_b_state:string;latest_event:AuditEvent|null;latest_entry:AuditEvent|null;latest_plus20:AuditEvent|null;latest_classifier:AuditEvent|null;latest_normal_b_proved?:AuditEvent|null;latest_normal_b_tier2?:AuditEvent|null;latest_normal_b_tier3?:AuditEvent|null;latest_normal_b_exit?:AuditEvent|null;latest_normal_b_unavailable?:AuditEvent|null;latest_degraded:AuditEvent|null;latest_recovery:AuditEvent|null;latest_rescue:AuditEvent|null;latest_reentry:AuditEvent|null;latest_terminal?:AuditEvent|null;safety:WorkspaceStatus['safety']}
type TimelineRow={event_id:string;session_date?:string|null;timestamp:string;event_type:string;family?:string|null;display_owner?:string|null;direction:string|null;state_before:string|null;state_after:string|null;result:string|null;reason:string|null;underlying_price:number|null;directional_points:number|null;nifty_points_from_entry?:number|null;nifty_entry_price?:number|null;reference_type?:string|null}
type ReplayPresentation={status:string;label:string;family:string|null;direction:string|null;entry_timestamp:string|null;entry_underlying:number|null;current_underlying:number|null;directional_move:number|null;plus20:boolean;classifier:string|null;degraded:boolean;recovered:boolean;option_intent:string|null;futures_close:number|null;futures_vwap:number|null;raw_vwap_diff:number|null;vwap_position:string}
type ReplayMinute={session_date:string;timestamp:string;underlying_open:number|null;underlying_high:number|null;underlying_low:number|null;underlying_close:number|null;futures_close:number|null;futures_vwap:number|null;nifty_points_from_entry?:number|null;nifty_entry_price?:number|null;data_status:string;events:TimelineRow[];presentation?:ReplayPresentation|null}
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

type OptionLeg={relation_to_atm:number;strike:number;side:string;expiry:string;instrument_key:string;entry_timestamp:string;entry_premium:number|null;latest_timestamp:string|null;latest_premium:number|null;exit_timestamp:string|null;exit_premium:number|null;pnl_points:number|null;pnl_pct:number|null;mfe_points:number|null;mae_points:number|null;status:string;issue?:string|null}
type OptionObservation={status:string;reason?:string;side?:string;as_of:string;entry_boundary?:string;legs:OptionLeg[]}

function ExactOptionObservation({sessionDate,asOf}:{sessionDate:string;asOf:string}){
 const [observation,setObservation]=useState<OptionObservation|null>(null)
 useEffect(()=>{let active=true;setObservation(null);const url=base+'/option-observation?session_date='+encodeURIComponent(sessionDate)+'&as_of='+encodeURIComponent(asOf);void fetch(url).then(async r=>{if(!r.ok)throw new Error('OPTION_OBSERVATION_REQUEST_FAILED');return r.json() as Promise<OptionObservation>}).then(x=>{if(active)setObservation(x)}).catch(()=>{if(active)setObservation({status:'UNAVAILABLE',reason:'OPTION_OBSERVATION_REQUEST_FAILED',as_of:asOf,legs:[]})});return()=>{active=false}},[sessionDate,asOf])
 return <section className="mp-exact-options"><div className="mp-section-title">EXACT {observation?.side??'CE / PE'} OPTION OBSERVATION · AS OF {tm(asOf)}</div>
  {!observation?<p>Loading exact option evidence…</p>:observation.status==='ENTRY_PENDING'||observation.status==='NO_ENTRY_YET'?<p>Option entry is not causally available at this minute.</p>:!observation.legs.length?<p>UNAVAILABLE · {words(observation.reason??'Exact option tape has not been materialized')}</p>:<><div className="shadow-table-scroll"><table className="shadow-table mp-option-table"><thead><tr><th>Leg</th><th>Instrument / expiry</th><th>Entry time</th><th>Entry ₹</th><th>Latest / exit time</th><th>Latest / exit ₹</th><th>P&amp;L pts</th><th>P&amp;L %</th><th>MFE pts</th><th>MAE pts</th><th>Status</th></tr></thead><tbody>{observation.legs.map(l=><tr key={l.instrument_key}><td>ATM {l.relation_to_atm>=0?'+':''}{l.relation_to_atm} {l.side}<small> · {num(l.strike,0)}</small></td><td>{l.instrument_key}<small> · {l.expiry}</small></td><td>{tm(l.entry_timestamp)}</td><td>{num(l.entry_premium)}</td><td>{tm(l.exit_timestamp??l.latest_timestamp)}</td><td>{num(l.exit_premium??l.latest_premium)}</td><td>{num(l.pnl_points)}</td><td>{num(l.pnl_pct)}{l.pnl_pct!=null?'%':''}</td><td>{num(l.mfe_points)}</td><td>{num(l.mae_points)}</td><td>{words(l.status)}{l.issue?<small> · {words(l.issue)}</small>:null}</td></tr>)}</tbody></table></div><small>Exact provider minutes; hypothetical premium points per independent contract. No order, quantity, or rupee P&amp;L.</small></>}
 </section>
}


function ageLabel(ts:string|null|undefined){
 if(!ts)return'—'
 const ms=Date.now()-Date.parse(ts)
 if(!Number.isFinite(ms))return'—'
 const s=Math.max(0,Math.floor(ms/1000))
 if(s<60)return`${s}s`
 const m=Math.floor(s/60)
 if(m<60)return`${m}m ${s%60}s`
 const h=Math.floor(m/60)
 return`${h}h ${m%60}m`
}

function sourceLabel(mode:'LIVE'|'HISTORICAL_REPLAY',source?:string|null){
 if(mode==='LIVE')return'LIVE SHADOW'
 if(source==='FORWARD_OOS_REPLAY')return'FORWARD OOS REPLAY · NO-REENTRY'
 if(source==='V57_PARITY_PROVEN_REPLAY')return'V57 PARITY-PROVEN REPLAY'
 return words(source)
}

function MidpointFreshnessHeader({
 mode,status,selectedDate,selectedSession,minutes,lastRefresh
}:{
 mode:'LIVE'|'HISTORICAL_REPLAY';
 status:Status|null;
 selectedDate:string;
 selectedSession?:Session;
 minutes:ReplayMinute[];
 lastRefresh:string|null;
}){
 const latestAudit=status?.latest_event?.event_timestamp??null
 const latestMarket=mode==='HISTORICAL_REPLAY'
   ?(minutes.at(-1)?.timestamp??null)
   :(status?.latest_event?.event_timestamp??null)
 const sessionDate=mode==='HISTORICAL_REPLAY'
   ?selectedDate
   :(status?.latest_event?.session_date??status?.session_dates?.at(-1)??'—')
 const stale=mode==='LIVE'&&latestMarket?Date.now()-Date.parse(latestMarket)>120000:false

 return <section className={`mp-freshness ${stale?'stale':''}`}>
   <div className="mp-freshness-title">
     <div>
       <span>LATEST MIDPOINT DETAILS</span>
       <b>{sessionDate}</b>
     </div>
     <strong>{sourceLabel(mode,selectedSession?.source)}</strong>
   </div>
   <div className="mp-freshness-grid">
     <article><span>Session / trading date</span><b>{sessionDate}</b></article>
     <article><span>Latest market/evidence time</span><b>{dt(latestMarket)}</b><small>{mode==='LIVE'?`age ${ageLabel(latestMarket)}`:'replay session end'}</small></article>
     <article><span>Latest strategy audit</span><b>{dt(latestAudit)}</b><small>{words(status?.latest_event?.event_type)}</small></article>
     <article><span>UI refreshed</span><b>{dt(lastRefresh)}</b><small>{mode==='LIVE'?'5-second polling':'manual / replay load'}</small></article>
     <article><span>Current owner</span><b>{semanticOwner(status?.latest_event??status?.latest_entry)}</b><small>{words(status?.latest_event?.direction)}</small></article>
     <article><span>Safety</span><b>{status?.safety.observation_only?'OBSERVATION ONLY':'CHECK'}</b><small>Execution {status?.safety.execution_enabled?'ON':'OFF'} · Paper {status?.safety.paper_order_enabled?'ON':'OFF'}</small></article>
   </div>
   {stale&&<div className="mp-stale-warning">Latest live evidence is older than 2 minutes. Treat the screen as stale until new evidence arrives.</div>}
 </section>
}

function CheckpointComparison({status}:{status:Status|null}){
 const rows=[
   ['ENTRY',status?.latest_entry],
   ['+20 PROOF',status?.latest_plus20],
   ['CLASSIFIER',status?.latest_classifier],
   ['DEGRADED',status?.latest_degraded],
   ['RECOVERY',status?.latest_recovery],
   ['CAP20',status?.latest_rescue],
   ['TERMINAL',status?.latest_terminal],
 ] as [string,AuditEvent|null|undefined][]
 const useful=rows.filter(([,e])=>!!e)
 if(!useful.length)return null
 return <section className="panel shadow-panel mp-checkpoint-panel">
   <div className="panel-heading"><div><h2>Lifecycle checkpoint comparison</h2><p>Compare the same trade at important state transitions without changing immutable audit evidence.</p></div><span className="pill teal">FORENSICS</span></div>
   <div className="shadow-table-scroll"><table className="shadow-table mp-checkpoint-table">
     <thead><tr><th>Checkpoint</th><th>Time</th><th>Owner</th><th>Direction</th><th>NIFTY</th><th>NIFTY pts from entry</th><th>Fut close</th><th>Fut VWAP</th><th>Raw diff</th><th>Result / reason</th></tr></thead>
     <tbody>{useful.map(([label,e])=>{
       const raw=e?.futures_price!=null&&e?.futures_vwap!=null?e.futures_price-e.futures_vwap:null
       return <tr key={label}><td><b>{label}</b></td><td>{tm(e?.event_timestamp)}</td><td>{semanticOwner(e)}</td><td>{words(e?.direction)}</td><td>{num(e?.underlying_price)}</td><td>{num(e?.nifty_points_from_entry)}</td><td>{num(e?.futures_price)}</td><td>{num(e?.futures_vwap)}</td><td>{raw==null?'—':`${raw>=0?'+':''}${num(raw)}`}</td><td>{words(e?.result||e?.reason)}</td></tr>
     })}</tbody>
   </table></div>
 </section>
}

function nextTransitionText(m:ReplayMinute){
 const p=m.presentation
 if(!p){
   if(m.events?.length)return'No active B/E position at this minute. Inspect the immutable event below to see why the strategy changed state or why ownership was assigned.'
   return'No active Midpoint position and no immutable strategy event at this minute.'
 }
 if(!p.plus20)return'Next management milestone: +20 proof — first favorable intrabar excursion of at least 20 underlying points.'
 if(!p.classifier)return'Next management milestone: exact +10-minute runner classifier after +20 proof. It checks positive directional progress and positive directional futures-VWAP change.'
 if(!p.degraded)return'Runner has been classified. Continue monitoring for joint deterioration: drawdown from running favorable excursion together with negative directional futures-VWAP change.'
 if(p.degraded&&!p.recovered)return'DEGRADED is active. Waiting for strict recovery through the degraded target before CAP20 rebreak timing can begin.'
 if(p.recovered)return'Recovery has occurred. After at least 10 minutes, the first strict rebreak of the degraded target is the CAP20 decision point; rescue is eligible only when directional move is <= +20.'
 return'Continue following the immutable lifecycle events.'
}

function MinuteExplainPanel({m}:{m:ReplayMinute}){
 const raw=m.futures_close!=null&&m.futures_vwap!=null?m.futures_close-m.futures_vwap:null
 const p=m.presentation
 return <div className="mp-minute-explain">
   <div className="mp-minute-explain-head"><div><span>EXPLAIN THIS MINUTE</span><b>{dt(m.timestamp)}</b></div><strong>{p?.label??(m.events?.length?words(m.events[0].event_type):'NO ACTIVE EVENT')}</strong></div>
   <div className="mp-minute-explain-grid">
     <article><span>NIFTY candle</span><b>{num(m.underlying_close)}</b><small>O {num(m.underlying_open)} · H {num(m.underlying_high)} · L {num(m.underlying_low)}</small></article>
     <article><span>Futures vs VWAP</span><b>{raw==null?'—':`${raw>=0?'+':''}${num(raw)}`}</b><small>{raw==null?'Unavailable':raw>0?'ABOVE VWAP':raw<0?'BELOW VWAP':'AT VWAP'}</small></article>
     <article><span>Lifecycle</span><b>{p?`${words(p.family)} · ${words(p.direction)}`:'—'}</b><small>{p?`Move ${num(p.directional_move)} · +20 ${yn(p.plus20)} · degraded ${yn(p.degraded)}`:'No active position'}</small></article>
     <article><span>Option intent</span><b>{p?.option_intent??'—'}</b><small>{p?'Exact basket attaches in M2.5B option observation.':'No active option intent'}</small></article>
   </div>
   <div className="mp-next-transition"><span>WHAT MUST HAPPEN NEXT</span><p>{nextTransitionText(m)}</p></div>
   {m.events?.length>0&&<div className="mp-explain-events"><span>IMMUTABLE EVENTS AT THIS MINUTE</span>{m.events.map(e=><b key={e.event_id}>{words(e.event_type)} · {semanticOwner(e)} · {words(e.result||e.reason)}</b>)}</div>}
   <ExactOptionObservation sessionDate={m.session_date} asOf={m.timestamp}/>
 </div>
}

function EventCard({label,event}:{label:string;event:AuditEvent|null|undefined}){return <article className={`mp-card ${eventClass(event?.event_type??'')}`}><span>{label}</span><b>{event?words(event.result||event.event_type):'—'}</b><small>{event?`${tm(event.event_timestamp)} · ${words(event.reason)} · NIFTY ${num(event.underlying_price)} · from entry ${num(event.nifty_points_from_entry)} pts`:'No event yet'}</small></article>}

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
   <section className="mp-evidence-card"><div className="mp-section-title">NIFTY / STRUCTURE</div><div className="mp-kv"><span>NIFTY</span><b>{num(ui?.market.nifty??event.underlying_price)}</b><span>Reference</span><b>{words(ui?.market.reference_type??event.reference_type)}</b><span>High</span><b>{num(ui?.market.reference_high??event.reference_high)}</b><span>Low</span><b>{num(ui?.market.reference_low??event.reference_low)}</b><span>Midpoint</span><b>{num(ui?.market.midpoint??event.midpoint)}</b><span>Boundary</span><b>{num(ui?.market.boundary??event.original_boundary)}</b><span>NIFTY entry</span><b>{num(event.nifty_entry_price)}</b><span>NIFTY pts from entry</span><b>{num(event.nifty_points_from_entry)}</b><span>Raw audit directional field</span><b>{num(event.directional_points)}</b></div></section>

   <section className="mp-evidence-card"><div className="mp-section-title">FUTURES / VWAP</div><div className="mp-kv"><span>Futures close</span><b>{num(ui?.vwap.futures_close??event.futures_price)}</b><span>Futures VWAP</span><b>{num(ui?.vwap.futures_vwap??event.futures_vwap)}</b><span>Raw futures − VWAP</span><b>{num(ui?.vwap.raw_diff)}</b><span>VWAP position</span><b className={ui?.vwap.position==='BELOW VWAP'?'mp-bear':ui?.vwap.position==='ABOVE VWAP'?'mp-bull':''}>{ui?.vwap.position??'—'}</b><span>Directional VWAP</span><b>{num(ui?.vwap.directional_value??event.directional_vwap_value)}</b></div></section>

   <section className="mp-evidence-card"><div className="mp-section-title">STRATEGY DECISION</div><div className="mp-kv"><span>Owner</span><b>{ui?.strategy.owner??semanticOwner(event)}</b><span>Direction</span><b>{words(ui?.strategy.direction??event.direction)}</b><span>Event</span><b>{words(ui?.strategy.event_type??event.event_type)}</b><span>Result</span><b>{words(ui?.strategy.result??event.result)}</b><span>Reason</span><b>{words(ui?.strategy.reason??event.reason)}</b></div></section>

   <section className="mp-evidence-card"><div className="mp-section-title">OPTION</div><div className="mp-kv"><span>Intent</span><b>{ui?.option.intent??'—'}</b><span>Expiry</span><b>{ui?.option.expiry??'Not selected'}</b><span>Strike</span><b>{ui?.option.strike??'Not selected'}</b><span>Instrument</span><b>{ui?.option.instrument_key??'Not selected'}</b><span>Entry premium</span><b>{num(ui?.option.entry_premium)}</b><span>Exit premium</span><b>{num(ui?.option.exit_premium)}</b></div><p className="mp-option-note">{ui?.option.note??'Exact option evidence is not available in the current Midpoint audit.'}</p></section>
  </div>

  <CheckTable title="STRUCTURE QUALIFICATION" rows={ui?.checks.structure}/>
  <CheckTable title="STRATEGY / OWNERSHIP QUALIFICATION" rows={ui?.checks.strategy}/>
  <CheckTable title="MANAGEMENT QUALIFICATION" rows={ui?.checks.management}/>
  <ExactOptionObservation sessionDate={event.session_date} asOf={event.event_timestamp}/>

  <details className="mp-raw-details"><summary>Decision evidence · raw</summary><pre>{JSON.stringify(event.evidence??{},null,2)}</pre></details>
  <details className="mp-raw-details"><summary>Raw immutable audit event</summary><pre>{JSON.stringify(event,null,2)}</pre></details>
 </div>
}

function LiveAuditTable({timeline,onInspect,selected,mode='LIVE'}:{timeline:TimelineRow[];onInspect:(id:string)=>void;selected:AuditEvent|null;mode?:'LIVE'|'HISTORICAL_REPLAY'}){return <section className="panel shadow-panel"><div className="panel-heading"><div><h2>Midpoint candle-by-candle decision audit</h2><p>{mode==='LIVE'?'Latest two available live sessions.':'Selected historical session.'} Inspect shows the same qualification detail in both views.</p></div><span className="pill teal">{mode==='LIVE'?'LIVE':'REPLAY'}</span></div><div className="shadow-table-scroll mp-table-scroll"><table className="shadow-table mp-table"><thead><tr><th>Time</th><th>Session</th><th>Event</th><th>Owner</th><th>Direction</th><th>State</th><th>Result</th><th>Reason</th><th>NIFTY</th><th>NIFTY pts from entry</th><th>Audit</th></tr></thead><tbody>{[...timeline].reverse().flatMap(x=>{const expanded=selected?.event_id===x.event_id;return [<tr key={x.event_id} className={eventClass(x.event_type)}><td>{tm(x.timestamp)}</td><td>{x.session_date??'—'}</td><td><b>{words(x.event_type)}</b></td><td>{semanticOwner(x)}</td><td>{words(x.direction)}</td><td>{words(x.state_after||x.state_before)}</td><td>{words(x.result)}</td><td className="mp-reason">{words(x.reason)}</td><td>{num(x.underlying_price)}</td><td>{num(x.nifty_points_from_entry)}</td><td><button className="secondary" aria-expanded={expanded} onClick={()=>onInspect(x.event_id)}>{expanded?'Collapse':'Inspect'}</button></td></tr>,expanded&&selected?<tr key={x.event_id+'-detail'} className="mp-inline-detail-row"><td colSpan={11}><div className="mp-inline-audit"><div className="mp-inline-audit-head"><div><span>DETAILED AUDIT</span><b>{words(selected.event_type)}</b><small>{dt(selected.event_timestamp)}</small></div><button className="secondary" onClick={()=>onInspect(x.event_id)}>Collapse</button></div><AuditDetail event={selected}/></div></td></tr>:null]})}{!timeline.length&&<tr><td colSpan={11} className="empty">No Midpoint audit evidence for this view.</td></tr>}</tbody></table></div></section>}


function eventMs(v:string|null|undefined){if(!v)return 0;const n=Date.parse(v);return Number.isFinite(n)?n:0}

function livePresentationFromStatus(status:Status|null):ReplayPresentation|null{
 const entry=status?.latest_entry
 if(!entry)return null

 const entryMs=eventMs(entry.event_timestamp)
 const terminalMs=eventMs(status?.latest_terminal?.event_timestamp)
 if(terminalMs>=entryMs)return null

 const latest=status?.latest_event
 const latestMs=eventMs(latest?.event_timestamp)
 const current=(latest&&latestMs>=entryMs)?latest:entry

 const direction=String(entry.direction??'')
 const entryPx=entry.underlying_price
 const currentPx=current?.underlying_price??entryPx
 let move:number|null=null
 if(entryPx!=null&&currentPx!=null){
   if(direction==='BULLISH')move=currentPx-entryPx
   else if(direction==='BEARISH')move=entryPx-currentPx
 }

 const fut=current?.futures_price??null
 const vwap=current?.futures_vwap??null
 const raw=fut!=null&&vwap!=null?fut-vwap:null

 const plus20=eventMs(status?.latest_plus20?.event_timestamp)>=entryMs
 const classifier=eventMs(status?.latest_classifier?.event_timestamp)>=entryMs
   ?(status?.latest_classifier?.result||status?.latest_classifier?.reason||null):null
 const degraded=eventMs(status?.latest_degraded?.event_timestamp)>=entryMs
 const recovered=eventMs(status?.latest_recovery?.event_timestamp)>=entryMs

 return {
   status:'ACTIVE',
   label:`CONTINUE · ${direction}_ACTIVE`,
   family:entry.family,
   direction,
   entry_timestamp:entry.event_timestamp,
   entry_underlying:entryPx,
   current_underlying:currentPx,
   directional_move:move,
   plus20,
   classifier,
   degraded,
   recovered,
   option_intent:direction==='BULLISH'?'BUY CE':direction==='BEARISH'?'BUY PE':null,
   futures_close:fut,
   futures_vwap:vwap,
   raw_vwap_diff:raw,
   vwap_position:raw==null?'NOT AVAILABLE':raw>0?'ABOVE VWAP':raw<0?'BELOW VWAP':'AT VWAP'
 }
}

function LiveContinuationPanel({status}:{status:Status|null}){
 const p=livePresentationFromStatus(status)
 if(!p)return null
 return <section className="panel shadow-panel mp-live-continuation-panel">
   <div className="panel-heading">
     <div>
       <h2>Live active continuation</h2>
       <p>Presentation-only projection from immutable live Midpoint audit state. No synthetic audit events are written.</p>
     </div>
     <span className="pill teal">LIVE ACTIVE</span>
   </div>
   <div className="mp-live-continuation-body">
     <ContinuationCard p={p}/>
     <div className="mp-live-kv">
       <span>Entry time</span><b>{tm(p.entry_timestamp)}</b>
       <span>Entry NIFTY</span><b>{num(p.entry_underlying)}</b>
       <span>Current NIFTY</span><b>{num(p.current_underlying)}</b>
       <span>Directional move</span><b>{num(p.directional_move)}</b>
       <span>Futures close</span><b>{num(p.futures_close)}</b>
       <span>Futures VWAP</span><b>{num(p.futures_vwap)}</b>
       <span>Raw futures − VWAP</span><b>{num(p.raw_vwap_diff)}</b>
       <span>VWAP position</span><b>{p.vwap_position}</b>
       <span>Option intent</span><b>{p.option_intent??'—'}</b>
       <span>+20 proof</span><b>{yn(p.plus20)}</b>
       <span>Classifier</span><b>{words(p.classifier)}</b>
       <span>Degraded</span><b>{yn(p.degraded)}</b>
     </div>
   </div>
 </section>
}

function ContinuationCard({p}:{p:ReplayPresentation}){
 return <div className={`mp-continuation ${p.status==='EXIT'?'exit':''}`}>
  <div><b>{p.label}</b><small>{words(p.family)} · {words(p.direction)} · {p.option_intent??'—'}</small></div>
  <div className="mp-continuation-metrics"><span>Move <b>{num(p.directional_move)}</b></span><span>VWAP <b>{p.vwap_position}</b></span><span>Raw diff <b>{num(p.raw_vwap_diff)}</b></span><span>+20 <b>{p.plus20?'YES':'NO'}</b></span><span>Classifier <b>{words(p.classifier)}</b></span><span>Degraded <b>{p.degraded?'YES':'NO'}</b></span></div>
 </div>
}

function ReplayMinuteTable({minutes,onInspect,selected}:{minutes:ReplayMinute[];onInspect:(id:string)=>void;selected:AuditEvent|null}){const[explained,setExplained]=useState<string|null>(null);return <section className="panel shadow-panel"><div className="panel-heading"><div><h2>Full-day minute replay</h2><p>Every minute remains evidence-faithful. Active continuation is a UI projection only; immutable audit events are unchanged.</p></div><span className="pill teal">REPLAY</span></div><div className="shadow-table-scroll mp-minute-scroll"><table className="shadow-table mp-minute-table"><thead><tr><th>Time</th><th>NIFTY O</th><th>H</th><th>L</th><th>C</th><th>NIFTY pts from entry</th><th>Fut close</th><th>Fut VWAP</th><th>Data</th><th>Strategy / continuation / audit</th></tr></thead><tbody>{minutes.flatMap(m=>{const first=m.events?.[0];const expanded=!!selected&&!!m.events?.some(e=>e.event_id===selected.event_id);return [<tr key={m.timestamp} className={first?eventClass(first.event_type):m.presentation?'mp-minute-active':'mp-minute-plain'}><td><b>{tm(m.timestamp)}</b></td><td>{num(m.underlying_open)}</td><td>{num(m.underlying_high)}</td><td>{num(m.underlying_low)}</td><td>{num(m.underlying_close)}</td><td>{num(m.nifty_points_from_entry)}</td><td>{num(m.futures_close)}</td><td>{num(m.futures_vwap)}</td><td><span className={'mp-data-status '+(m.data_status!=='BOTH'?'warn':'')}>{words(m.data_status)}</span></td><td>{m.presentation&&<ContinuationCard p={m.presentation}/>} <div className="mp-minute-actions"><button className="secondary mp-explain-btn" aria-expanded={explained===m.timestamp} onClick={()=>setExplained(explained===m.timestamp?null:m.timestamp)}>{explained===m.timestamp?'Close explanation':'Explain minute'}</button></div>{m.events?.length?<div className="mp-minute-events">{m.events.map(e=><div className="mp-minute-event" key={e.event_id}><div><b>{words(e.event_type)}</b><small>{semanticOwner(e)} · {words(e.direction)} · {words(e.result)}</small><small>{words(e.reason)} · NIFTY {num(e.underlying_price)} · from entry {num(e.nifty_points_from_entry)} pts</small></div><button className="secondary" aria-expanded={selected?.event_id===e.event_id} onClick={()=>onInspect(e.event_id)}>{selected?.event_id===e.event_id?'Collapse':'Inspect'}</button></div>)}</div>:!m.presentation?<span className="mp-no-event">—</span>:null}</td></tr>,explained===m.timestamp?<tr key={m.timestamp+'-explain'} className="mp-inline-detail-row"><td colSpan={10}><MinuteExplainPanel m={m}/></td></tr>:expanded&&selected?<tr key={m.timestamp+'-detail'} className="mp-inline-detail-row"><td colSpan={10}><div className="mp-inline-audit"><div className="mp-inline-audit-head"><div><span>DETAILED AUDIT</span><b>{words(selected.event_type)}</b><small>{dt(selected.event_timestamp)}</small></div><button className="secondary" onClick={()=>onInspect(selected.event_id)}>Collapse</button></div><AuditDetail event={selected}/></div></td></tr>:null]})}{!minutes.length&&<tr><td colSpan={10} className="empty">No full-day minute evidence materialized for this date.</td></tr>}</tbody></table></div></section>}


function ActiveTradeSection({status}:{status:Status|null}){
 const entry=status?.latest_entry
 if(!entry)return <section className="mp-trade-strip mp-trade-strip-empty"><div><span>ACTIVE TRADE</span><b>NO ACTIVE TRADE</b></div><small>Waiting for a valid B/E entry.</small></section>

 const entryMs=eventMs(entry.event_timestamp)
 const terminal=status?.latest_terminal
 const terminalMs=eventMs(terminal?.event_timestamp)
 if(terminalMs>=entryMs)return <section className="mp-trade-strip mp-trade-strip-empty"><div><span>ACTIVE TRADE</span><b>NO ACTIVE TRADE</b></div><small>Latest trade lifecycle is closed.</small></section>

 const latest=status?.latest_event
 const currentPx=latest?.underlying_price??entry.underlying_price
 const direction=String(entry.direction??'')
 const move=entry.underlying_price!=null&&currentPx!=null
   ?(direction==='BULLISH'?currentPx-entry.underlying_price:
     direction==='BEARISH'?entry.underlying_price-currentPx:null)
   :null
 const fut=latest?.futures_price??entry.futures_price
 const vwap=latest?.futures_vwap??entry.futures_vwap
 const raw=fut!=null&&vwap!=null?fut-vwap:null
 const optionIntent=direction==='BULLISH'?'BUY CE':direction==='BEARISH'?'BUY PE':'—'

 return <section className="mp-trade-strip active">
   <div className="mp-trade-strip-title"><span>ACTIVE TRADE</span><b>{words(entry.family)} · {words(direction)} · {optionIntent}</b></div>
   <div className="mp-trade-strip-grid">
     <article><span>Entry time</span><b>{tm(entry.event_timestamp)}</b></article>
     <article><span>Entry NIFTY</span><b>{num(entry.underlying_price)}</b></article>
     <article><span>Current NIFTY</span><b>{num(currentPx)}</b></article>
     <article><span>Directional move</span><b>{num(move)}</b></article>
     <article><span>Fut / VWAP</span><b>{num(fut)} / {num(vwap)}</b><small>{raw==null?'—':raw>0?'ABOVE VWAP':raw<0?'BELOW VWAP':'AT VWAP'}</small></article>
     <article><span>+20</span><b>{eventMs(status?.latest_plus20?.event_timestamp)>=entryMs?'YES':'NO'}</b></article>
     <article><span>Classifier</span><b>{eventMs(status?.latest_classifier?.event_timestamp)>=entryMs?words(status?.latest_classifier?.result||status?.latest_classifier?.reason):'WAITING'}</b></article>
     <article><span>Degraded</span><b>{eventMs(status?.latest_degraded?.event_timestamp)>=entryMs?'YES':'NO'}</b></article>
   </div>
 </section>
}

function ExitDetailsSection({status}:{status:Status|null}){
 const terminal=status?.latest_terminal
 const rescue=status?.latest_rescue
 const exit=(terminal&&eventMs(terminal.event_timestamp)>=eventMs(rescue?.event_timestamp))?terminal:rescue
 if(!exit)return <section className="mp-exit-strip mp-exit-strip-empty"><div><span>EXIT DETAILS</span><b>NO EXIT YET</b></div><small>No completed Midpoint exit is available for this view.</small></section>

 return <section className="mp-exit-strip">
   <div className="mp-trade-strip-title"><span>EXIT DETAILS</span><b>{words(exit.event_type)}</b></div>
   <div className="mp-trade-strip-grid">
     <article><span>Exit time</span><b>{tm(exit.event_timestamp)}</b></article>
     <article><span>Owner / family</span><b>{semanticOwner(exit)}</b></article>
     <article><span>Direction</span><b>{words(exit.direction)}</b></article>
     <article><span>NIFTY at exit</span><b>{num(exit.underlying_price)}</b></article>
     <article><span>NIFTY pts from entry</span><b>{num(exit.nifty_points_from_entry)}</b></article>
     <article><span>Futures close</span><b>{num(exit.futures_price)}</b></article>
     <article><span>Futures VWAP</span><b>{num(exit.futures_vwap)}</b></article>
     <article><span>Reason</span><b>{words(exit.reason||exit.result)}</b></article>
   </div>
 </section>
}

function SessionView({mode,status,timeline,minutes,selected,onInspect}:{mode:'LIVE'|'HISTORICAL_REPLAY';status:Status|null;timeline:TimelineRow[];minutes:ReplayMinute[];selected:AuditEvent|null;onInspect:(id:string)=>void}){
 const current=status?.latest_event
 return <>
 <div className="shadow-safety"><b>MIDPOINT STRATEGY · {mode==='LIVE'?'OBSERVATION ONLY':'HISTORICAL REPLAY'}</b><span>Execution disabled</span><span>Paper orders disabled</span><span>Quantity none</span><span>{mode==='LIVE'?'Current + previous available trading session':'One selected trading date'}</span></div>
 <div className="shadow-metrics mp-summary mp-summary-compact"><article><span>Owner</span><b>{semanticOwner(current??status?.latest_entry)}</b><small>FRESH A = fresh Candidate A owns boundary; not B/E</small></article><article><span>Direction</span><b>{words(current?.direction)}</b><small>{words(current?.reference_type)} reference</small></article><article><span>Family state</span><b>{words(status?.family_b_state)}</b><small>{status?.audit_record_count??0} strategy events</small></article><article><span>Latest event</span><b>{words(current?.event_type)}</b><small>{tm(current?.event_timestamp)}</small></article><article><span>Boundary / midpoint</span><b>{num(current?.original_boundary)} / {num(current?.midpoint)}</b><small>High {num(current?.reference_high)} · Low {num(current?.reference_low)}</small></article><article><span>Safety</span><b>{status?.safety.observation_only?'SAFE':'CHECK'}</b><small>Execution {status?.safety.execution_enabled?'ON':'OFF'} · Paper {status?.safety.paper_order_enabled?'ON':'OFF'}</small></article></div>
 <div className="mp-lifecycle-grid mp-lifecycle-compact"><EventCard label="Entry" event={status?.latest_entry}/><EventCard label="+20 proof" event={status?.latest_plus20}/><EventCard label="Runner classification" event={status?.latest_classifier}/><EventCard label="Degraded" event={status?.latest_degraded}/><EventCard label="CAP20 rescue" event={status?.latest_rescue}/><EventCard label="Structural terminal" event={status?.latest_terminal}/></div>
 <div className="mp-lifecycle-grid mp-lifecycle-compact"><EventCard label="Normal-B proved" event={status?.latest_normal_b_proved}/><EventCard label="Tier 2 · +15 floor" event={status?.latest_normal_b_tier2}/><EventCard label="Tier 3 · close ratchet" event={status?.latest_normal_b_tier3}/><EventCard label="Normal-B candidate exit" event={status?.latest_normal_b_exit??status?.latest_normal_b_unavailable}/></div>
 <ActiveTradeSection status={status}/>
 {mode==='LIVE'&&<LiveContinuationPanel status={status}/>}
 <LiveAuditTable timeline={timeline} onInspect={onInspect} selected={selected} mode={mode}/>{mode==='HISTORICAL_REPLAY'&&<ReplayMinuteTable minutes={minutes} onInspect={onInspect} selected={selected}/>}
 <ExitDetailsSection status={status}/>
 </>
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
 const [lastRefresh,setLastRefresh]=useState<string|null>(null)

 const refreshLive=async(active:()=>boolean)=>{try{const s=await get<Status>('/status');if(!active())return;setStatus(s);setMinutes([]);setLastRefresh(new Date().toISOString());setError('');setLoading(false);const t=await get<{timeline:TimelineRow[]}>('/timeline?limit=200');if(active())setTimeline(t.timeline)}catch(e){if(active())setError((e as Error).message)}finally{if(active())setLoading(false)}}
 const fetchReplay=async(date:string)=>{if(!date)return;setLoading(true);setSelected(null);try{const r=await get<HistResponse>('/historical/session?session_date='+encodeURIComponent(date));setSelectedDate(date);setStatus(r.status);setTimeline(r.timeline);setMinutes(r.minutes??[]);setLastRefresh(new Date().toISOString());setError('')}catch(e){setError((e as Error).message)}finally{setLoading(false)}}

 useEffect(()=>{if(mode!=='LIVE')return;let active=true;let inFlight=false;const poll=async()=>{if(!active||inFlight||document.hidden)return;inFlight=true;try{await refreshLive(()=>active)}finally{inFlight=false}};void poll();const id=window.setInterval(()=>void poll(),5000);return()=>{active=false;window.clearInterval(id)}},[mode])
 useEffect(()=>{if(mode!=='HISTORICAL_REPLAY')return;let active=true;setLoading(true);void (async()=>{try{const r=await get<{sessions:Session[]}>('/historical/sessions');if(!active)return;const available=r.sessions??[];setSessions(available);const date=available.some(x=>x.session_date===selectedDate)?selectedDate:(available[0]?.session_date??'');setSelectedDate(date);if(date){const replay=await get<HistResponse>('/historical/session?session_date='+encodeURIComponent(date));if(!active)return;setStatus(replay.status);setTimeline(replay.timeline);setMinutes(replay.minutes??[]);setLastRefresh(new Date().toISOString());setError('')}else{setStatus(null);setTimeline([]);setMinutes([])}}catch(e){if(active)setError((e as Error).message)}finally{if(active)setLoading(false)}})();return()=>{active=false}},[mode])

 const inspect=async(eventId:string)=>{if(selected?.event_id===eventId){setSelected(null);return}try{const path=mode==='LIVE'?'/audit-detail?event_id='+encodeURIComponent(eventId):'/historical/audit-detail?session_date='+encodeURIComponent(selectedDate)+'&event_id='+encodeURIComponent(eventId);const r=await get<{event:AuditEvent}>(path);setSelected(r.event);setError('')}catch(e){setError((e as Error).message)}}
 const latestSessions=useMemo(()=>status?.session_dates??[],[status])
 const orderedDates=useMemo(()=>sessions.map(x=>x.session_date).sort(),[sessions])
 const selectedIndex=orderedDates.indexOf(selectedDate)
 const previousDate=selectedIndex>0?orderedDates[selectedIndex-1]:''
 const nextDate=selectedIndex>=0&&selectedIndex<orderedDates.length-1?orderedDates[selectedIndex+1]:''
 const selectedSession=sessions.find(x=>x.session_date===selectedDate)
 const replaySource=selectedSession?.source==='FORWARD_OOS_REPLAY'?'FORWARD OOS REPLAY · NO-REENTRY BASELINE':selectedSession?.source==='V57_PARITY_PROVEN_REPLAY'?'V57 PARITY-PROVEN REPLAY':words(selectedSession?.source)

 return <div className="shadow-page hilega-page midpoint-page">{error&&<div role="alert" className="banner error">{error}</div>}<div className="mp-modebar"><div><button className={mode==='LIVE'?'primary':'secondary'} onClick={()=>{setMode('LIVE');setSelected(null);setLoading(true)}}>Live shadow</button><button className={mode==='HISTORICAL_REPLAY'?'primary':'secondary'} onClick={()=>{setMode('HISTORICAL_REPLAY');setSelected(null);setLoading(true)}}>Historical replay</button></div>{mode==='LIVE'?<small>Visible sessions: {latestSessions.length?latestSessions.join(' + '):'waiting for audit'}</small>:<div className="mp-replay-controls"><button className="secondary" disabled={!previousDate||loading} onClick={()=>void fetchReplay(previousDate)}>← Previous date</button><select value={selectedDate} disabled={loading&&!sessions.length} onChange={e=>void fetchReplay(e.target.value)}>{!sessions.length&&<option value="">No materialized sessions</option>}{sessions.map(x=><option key={x.session_date} value={x.session_date}>{x.session_date} · {x.minute_count??0} min · {x.event_count??0} events</option>)}</select><button className="secondary" disabled={!nextDate||loading} onClick={()=>void fetchReplay(nextDate)}>Next date →</button><button className="primary" disabled={!selectedDate||loading} onClick={()=>void fetchReplay(selectedDate)}>{loading?'Loading…':'Reload date'}</button></div>}</div><MidpointFreshnessHeader mode={mode} status={status} selectedDate={selectedDate} selectedSession={selectedSession} minutes={minutes} lastRefresh={lastRefresh}/>{mode==='HISTORICAL_REPLAY'&&selectedDate&&<div className="mp-replay-banner"><b>HISTORICAL REPLAY</b><span>{selectedDate}</span><span>{minutes.length}/360 minute rows</span><span>{timeline.length} strategy events</span><small>{minutes.length===360&&minutes.every(m=>m.data_status==='BOTH')?'Complete NIFTY + futures minutes':'Check minute coverage'}</small><small>{selectedSession?.block??'tested source'} · {replaySource} · manual validation · no broker / no execution</small></div>}{loading&&!status?<section className="panel"><div className="empty">Loading Midpoint Strategy…</div></section>:<SessionView mode={mode} status={status} timeline={timeline} minutes={minutes} selected={selected} onInspect={id=>void inspect(id)}/>}<CheckpointComparison status={status}/></div>
}
