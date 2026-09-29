import { useEffect, useRef, useState } from 'react'
import type { Config, Detail, Point, Result, State } from './types'
import { fetchLatestPanelTrends, type PCRTrendResult } from './pcrTrends'
import { fetchStrikePositioning, type PositioningClassification, type PositioningHorizon, type StrikePositioningResult } from './strikePositioning'
import HistoricalResearch from './historicalResearch'
import LiveShadowMonitor from './liveShadow'
import HilegaMilegaShadow from './hilegaMilegaShadow'
import HistoricalReplay from './historicalReplay'

const number = (v: number|null|undefined, digits = 0) => v == null ? '—' : v.toLocaleString('en-IN', {maximumFractionDigits: digits})
const time = (v: string) => new Date(v).toLocaleTimeString('en-IN', {timeZone: 'Asia/Kolkata', hour12: false})
const dateTime = (v: string) => new Date(v).toLocaleString('en-IN', {timeZone: 'Asia/Kolkata', hour12: false})
const words = (v: string) => v.replaceAll('_', ' ')
const titles = {fixed: 'Fixed morning ATM', moving: 'Moving ATM', full: 'Full expiry chain'}
const colors = {fixed: '#52dac0', moving: '#a499ff', full: '#8d9eae'}
const signed = (v: number|null|undefined, digits = 0) => v == null ? '—' : `${v > 0 ? '+' : ''}${number(v, digits)}`

async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, body === undefined ? undefined : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  })
  if (!response.ok) {
    const value = await response.json().catch(() => null)
    throw new Error(typeof value?.detail === 'string' ? value.detail : 'Request failed. Check configuration and backend.')
  }
  return response.json()
}

function Chart({points, selected, onSelect}: {points: Point[]; selected: number|null; onSelect: (id:number)=>void}) {
  const values = points.flatMap(p => p.evaluation.results.map(r => r.pcr).filter((v): v is number => v !== null))
  if (!values.length) return <div className="empty">No valid PCR observations yet. Start the collector or load the documented demo session.</div>
  const low = Math.min(...values, 1) - .06, high = Math.max(...values, 1) + .06
  const x = (i: number) => 55 + i * 865 / Math.max(1, points.length - 1)
  const y = (v: number) => 220 - (v - low) / (high - low) * 185
  return <svg viewBox="0 0 960 270" role="img" aria-label="PCR comparison. Use the observation selector below to inspect a point.">
    {[0,1,2,3,4].map(i => {const value = low + (high-low)*i/4; return <g key={i}>
      <line x1="55" x2="920" y1={y(value)} y2={y(value)} stroke="#25343f" strokeDasharray="3 5"/>
      <text x="8" y={y(value)+4}>{value.toFixed(2)}</text></g>})}
    {points.map((p,i) => p.range_changed && <line key={p.id} x1={x(i)} x2={x(i)} y1="25" y2="224" stroke="#7769c4" opacity=".35"/>)}
    {(['full','fixed','moving'] as const).map(mode => {
      let path = '', penDown = false
      points.forEach((p,i) => {
        const value = p.evaluation.results.find(r => r.mode === mode)?.pcr
        if (value == null) {penDown = false; return}
        if (i > 0 && p.evaluation.observed_at.slice(0,10) !== points[i-1].evaluation.observed_at.slice(0,10)) penDown = false
        path += `${penDown ? 'L':'M'}${x(i)},${y(value)} `; penDown = true
      })
      return <path key={mode} d={path} fill="none" stroke={colors[mode]} strokeWidth={mode === 'full' ? 1.5 : 2.5}/>
    })}
    {points.map((p,i) => <rect key={p.id} x={x(i)-Math.max(3,430/points.length)} y="25" width={Math.max(6,860/points.length)}
      height="200" fill={p.id===selected ? '#ffffff10':'transparent'} onClick={() => onSelect(p.id)} className="chart-hit">
      <title>{dateTime(p.evaluation.observed_at)} · select observation {p.id}</title></rect>)}
    <text x="55" y="252">{time(points[0].evaluation.observed_at)}</text>
    <text x="920" y="252" textAnchor="end">{time(points.at(-1)!.evaluation.observed_at)} IST</text>
  </svg>
}

export default function App() {
  const [state, setState] = useState<State|null>(null)
  const [draft, setDraft] = useState<Config|null>(null)
  const [tab, setTab] = useState('PCR workspace')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<number|null>(null)
  const [detail, setDetail] = useState<Detail|null>(null)
  const [pcrDisplay, setPcrDisplay] = useState<{configId:number;latest:Point|undefined;trends:PCRTrendResult[]}|null>(null)
  const pcrRequestGeneration = useRef(0)
  const pcrRequestKey = useRef<string|null>(null)
  const [positioningView, setPositioningView] = useState<'moving'|'fixed'|'full'>('moving')
  const [positioningHorizon, setPositioningHorizon] = useState<PositioningHorizon>(300)
  const [positioning, setPositioning] = useState<StrikePositioningResult[]>([])
  const [positioningState, setPositioningState] = useState<'loading'|'refreshing'|'ready'|'error'>('loading')
  const positioningContext = useRef<string|null>(null)
  const positioningRequestGeneration = useRef(0)
  const [schema, setSchema] = useState<Record<string, {minimum?: number; maximum?: number}>>({})
  const refreshPcr = (data:State) => {
    const candidate = data.history.at(-1)
    const requestKey = `${data.config_id}|${candidate?.id ?? 'none'}`
    if (pcrRequestKey.current === requestKey) return
    pcrRequestKey.current = requestKey
    const generation = ++pcrRequestGeneration.current
    setPcrDisplay(previous => ({
      configId: data.config_id,
      latest: candidate,
      trends: previous?.configId === data.config_id ? previous.trends : [],
    }))
    void fetchLatestPanelTrends(data.config_id)
      .then(value => {
        if (generation === pcrRequestGeneration.current) {
          setPcrDisplay({configId:data.config_id, latest:candidate, trends:value})
        }
      })
      .catch(error => {
        if (generation === pcrRequestGeneration.current) {
          pcrRequestKey.current = null
          setError((error as Error).message)
        }
      })
  }
  const refresh = async () => {
    const data = await api<State>('/state')
    setState(data); setDraft(old => old ?? data.config)
    refreshPcr(data)
  }
  useEffect(() => {
    let active = true
    const poll = async () => {
      try {
        const data = await api<State>('/state')
        if (active) {setState(data); setDraft(old=>old ?? data.config); setError('')}
        if (active) refreshPcr(data)
      }
      catch (e) {if(active) setError((e as Error).message)}
    }
    void poll()
    void api<{properties: typeof schema}>('/config-schema').then(s => {if(active) setSchema(s.properties)}).catch(()=>{})
    const timer = setInterval(poll, 3000)
    return () => {active = false; clearInterval(timer)}
  }, [])
  const latest = state?.history.at(-1)
  const displayedPcr = pcrDisplay?.configId===state?.config_id ? pcrDisplay : null
  const pcrLatest = displayedPcr?.latest
  const trends = displayedPcr?.trends ?? []
  const movingPositioningAtm = latest?.evaluation.results.find(result=>result.mode==='moving')?.atm ?? null
  const fixedPositioningAtm = latest?.evaluation.results.find(result=>result.mode==='fixed')?.atm ?? null
  const requestedPositioningAtm = positioningView==='moving' ? movingPositioningAtm : positioningView==='fixed' ? fixedPositioningAtm : null
  const positioningKey = state ? [state.config_id,positioningHorizon,positioningView,requestedPositioningAtm??'none',positioningView==='full'?0:5].join('|') : ''
  const detailId = selected ?? latest?.id
  useEffect(() => {
    if (!state) return
    if (positioningView==='fixed' && fixedPositioningAtm==null) {
      positioningRequestGeneration.current += 1
      positioningContext.current = positioningKey
      setPositioning([]); setPositioningState('ready'); return
    }
    let active = true
    const sameContext = positioningContext.current === positioningKey
    positioningContext.current = positioningKey
    const generation = ++positioningRequestGeneration.current
    if (!sameContext) setPositioning([])
    setPositioningState(sameContext ? 'refreshing' : 'loading')
    void fetchStrikePositioning(
      state.config_id, positioningHorizon,
      positioningView==='full' ? undefined : requestedPositioningAtm ?? undefined,
      positioningView==='full' ? undefined : 5,
    )
      .then(value => {if (active && generation===positioningRequestGeneration.current) {setPositioning(value); setPositioningState('ready')}})
      .catch(() => {if (active && generation===positioningRequestGeneration.current) setPositioningState('error')})
    return () => {active = false}
  }, [state?.config_id, latest?.id, positioningHorizon, positioningView, requestedPositioningAtm, fixedPositioningAtm, positioningKey])
  useEffect(() => {
    let active = true
    setDetail(null)
    if (detailId) void api<Detail>('/observations/' + detailId).then(d=>{if(active) setDetail(d)}).catch(e=>{if(active) setError(e.message)})
    return () => {active=false}
  }, [detailId])
  const action = async (work: ()=>Promise<void>) => {
    setBusy(true); setNotice(''); setError('')
    try {await work(); await refresh()} catch(e) {setError((e as Error).message)} finally {setBusy(false)}
  }
  const save = () => action(async () => {
    const result = await api<{message: string}>('/configurations', draft)
    setSelected(null); setNotice(result.message); setTab('PCR workspace')
  })
  const runReplay = () => action(async () => {
    const result = await api<{matched:boolean; observations:number; mismatches:number[]; message:string}>('/replay/' + state!.config_id, {})
    setNotice(result.observations === 0 ? result.message : result.matched
      ? `Replay matched all ${result.observations} recorded observations. This verifies calculations, not trading performance.`
      : `Replay found ${result.mismatches.length} mismatches. Inspect engine version before using these results.`)
  })
  const exportDetail = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(detail,null,2)], {type:'application/json'}))
    const a = document.createElement('a'); a.href=url; a.download=`observation-${detail!.id}.json`; a.click()
    URL.revokeObjectURL(url)
  }
  if (!state || !draft) return <main className="loading"><div className="brand-icon">M</div><h1>Market Strategy Lab</h1><p>{error || 'Connecting to the research workspace…'}</p><p>Start the local backend on port 8000.</p></main>
  const isDemo = state.config.provider === 'demo'
  return <div className="shell">
    <aside><div className="brand"><span className="brand-icon">M</span><div>MARKET LAB<small>STRATEGY RESEARCH</small></div></div>
      <div className="nav-label">WORKSPACE</div><nav>{['PCR workspace','Live shadow','Hilega shadow','Historical replay','Historical research','Data health','Configuration'].map(label =>
        <button key={label} className={tab===label ? 'active':''} onClick={()=>setTab(label)}><span>{label==='PCR workspace'?'◈':label==='Live shadow'?'◎':label==='Hilega shadow'?'◉':label==='Historical replay'?'↺':label==='Historical research'?'◫':label==='Data health'?'◉':'⚙'}</span>{label}</button>)}</nav>
      <div className="sidebar-bottom"><span className="dot"/><b>Research foundation</b><p>Record. Inspect. Reproduce.</p><small>Order execution is not enabled.</small></div>
    </aside>
    <main>
      <header><div className="breadcrumb">Research / <b>{tab}</b></div><span className={'pill ' + (isDemo?'amber':'teal')}>{isDemo?'SYNTHETIC DEMO':'UPSTOX DATA'}</span></header>
      <div className="page-heading"><div><div className="eyebrow">OPTIONS INTELLIGENCE</div><h1>{tab}</h1><p>{tab==='PCR workspace'?'One option chain. Two ATM perspectives. Every calculation traceable.':tab==='Live shadow'?'Observation-only strategy lifecycle, data health, entries, exits and P&L.':tab==='Hilega shadow'?'Hilega-Milega canonical live shadow with ATM±2 lifecycle and detailed audit drill-down.':tab==='Historical replay'?'Replay the current Live Shadow strategy candle-by-candle with full causal audit.':tab==='Historical research'?'Reconstruct Fixed, Moving, and Full PCR from expired option candles.':tab==='Data health'?'Connection health and data quality, with their limits visible.':'Versioned parameters for repeatable research.'}</p></div>
        {tab!=='Historical research' && tab!=='Live shadow' && tab!=='Hilega shadow' && tab!=='Historical replay' && <button disabled={busy} className={state.enabled?'secondary':'primary'} onClick={()=>void action(async()=>{
          await api('/collection',{enabled:!state.enabled})
          setNotice(state.enabled?'Pause requested. An in-flight observation may still finish.':'Collection requested. The separate worker must be running.')
        })}>{state.enabled?'Pause collection':'Start collection'}</button>}</div>
      {error && <div role="alert" className="banner error">{error} Displayed observations may be outdated.</div>}
      {notice && <div role="status" className="banner">{notice}</div>}
      {isDemo && <div className="demo-strip"><span>DEMO ENVIRONMENT</span>Generated prices and OI · simulated session clock · no market connection</div>}
      {!isDemo && <div className="demo-strip"><span>OI FRESHNESS UNKNOWN</span>Recent retrieval does not establish when exchange OI last changed.</div>}
      <div className="recording-status">{state.enabled ? (state.worker.alive ? (state.collection_overdue ? 'Collection overdue' : words(state.worker.state)) : 'Collector offline') : 'Collection paused / historical observations'} / Last recorded {state.receipt_age_seconds === null ? 'never' : number(state.receipt_age_seconds) + 's ago'}{latest ? ' / Observation ' + dateTime(latest.evaluation.observed_at) + ' IST' : ''}</div>
      {tab === 'PCR workspace' && <>
        <div className="instrument-bar"><div><b>{state.config.underlying.split('|').at(-1)}</b><span>EXPIRY {state.config.expiry}</span></div>
          <div>ATM ±{state.config.wings} strikes <i/> Anchor {state.config.anchor_time} IST <i/> Configuration v{state.config_id}</div></div>
        <div className="metrics">{(['fixed','moving','full'] as const).map(mode=>{
          const rawResult = pcrLatest?.evaluation.results.find(r=>r.mode===mode)
          const result = mode==='fixed' ? displayFixedResult(pcrLatest,rawResult) : rawResult
          const trendAt = (horizon: 300|900|1800) => {
            const existing = trends.find(trend =>
              trend.mode === mode && trend.requested_horizon_seconds === horizon)

            return mode === 'fixed'
              ? fixedSessionTrend(pcrLatest, horizon, existing)
              : existing
          }
          const fiveMinute = trendAt(300)
          const fifteenMinute = trendAt(900)
          const thirtyMinute = trendAt(1800)
          return <article className="metric" key={mode} style={{borderTopColor:colors[mode]}}>
            <div className="metric-title"><span>{titles[mode]}</span><span className="mini-dot" style={{background:colors[mode]}}/></div>
            <div className="metric-value"><span className="metric-current-label">Current PCR</span>{result?.pcr == null ? '—' : result.pcr.toFixed(3)}</div>
            <div className="trend-metrics">
              <span>5m Change <b>{signed(fiveMinute?.absolute_pcr_change, 2)}</b></span>
              <span>15m Change <b>{signed(fifteenMinute?.absolute_pcr_change, 2)}</b></span>
              <span>30m Change <b>{signed(thirtyMinute?.absolute_pcr_change, 2)}</b></span>
              <span>5m Trend <b>{fiveMinute?.classification ?? 'UNAVAILABLE'}</b></span>
            </div>
            <div className="metric-sub">{mode==='full'?'All catalog strikes':`ATM ${number(result?.atm)}`}<span>{result ? `${result.received}/${result.expected} contracts` : 'Awaiting data'}</span></div>
            {result?.issues.length ? <p className="issue">{result.issues.map(words).join(' · ')}</p> : <p>Put OI ÷ Call OI</p>}
          </article>
        })}</div>
        <StrikePositioning records={positioning} status={positioningState} view={positioningView} horizon={positioningHorizon}
          movingAtm={movingPositioningAtm}
          fixedAtm={fixedPositioningAtm}
          onView={setPositioningView} onHorizon={setPositioningHorizon}/>
        <section className="panel"><div className="panel-heading"><div><h2>PCR through the session</h2><p>{state.observation_count} recorded observations · showing latest {state.history.length}</p></div><button disabled={busy || !state.history.length} onClick={()=>void runReplay()}>Verify replay ↗</button></div>
          <div className="legend">{Object.entries(titles).map(([k,v])=><span key={k}><i style={{background:colors[k as keyof typeof colors]}}/>{v}</span>)}<small>Vertical markers: moving range or session changed</small></div>
          <Chart points={state.history} selected={detailId ?? null} onSelect={setSelected}/>
        </section>
        <section className="panel"><div className="panel-heading"><div><h2>Observation inspector</h2><p>Select a chart point to inspect the exact inputs.</p></div><select aria-label="Observation" value={selected ?? ''} onChange={e=>setSelected(e.target.value?Number(e.target.value):null)}>
          <option value="">Follow latest observation</option>{[...state.history].reverse().map(p=><option key={p.id} value={p.id}>#{p.id} · {dateTime(p.evaluation.observed_at)}</option>)}</select></div>
          {detail ? <>
            <div className="inspector-meta"><span>Spot <b>{number(detail.snapshot.spot,2)}</b></span><span>Observed <b>{dateTime(detail.snapshot.received_at)} IST</b></span><span>Anchor <b>{displayAnchorStatus(detail)}</b></span><button onClick={exportDetail}>Export inputs ↓</button></div>
            <div className="oi-sections">{detail.evaluation.results.map(result=>
              result.mode==='fixed' && fixedSessionUi(detail)
                ? <FixedSessionOISection key={result.mode} detail={detail}/>
                : <OISection key={result.mode} detail={detail} result={result}/>
            )}</div>
            <div className="panel-foot">OI units: {detail.snapshot.oi_unit} · Engine {detail.evaluation.engine_version} · Configuration v{detail.config_id}</div>
          </> : <div className="empty">No observation selected.</div>}
        </section>
      </>}
      {tab==='Live shadow' && <LiveShadowMonitor/>}
      {tab==='Hilega shadow' && <HilegaMilegaShadow/>}
      {tab==='Historical replay' && <HistoricalReplay/>}
      {tab==='Historical research' && <HistoricalResearch defaultUnderlying={state.config.underlying} defaultExpiry={state.config.expiry} defaultWings={state.config.wings}/>}
      {tab==='Data health' && <>
        <div className="health-grid">
          <Health label="Collector" value={state.worker.alive?words(state.worker.state):'Worker offline'} note="Heartbeat measures worker availability, not market freshness."/>
          <Health label="Last recording" value={state.receipt_age_seconds===null?'No data':number(state.receipt_age_seconds)+' seconds ago'} note={state.collection_overdue?'Collection overdue. Existing records remain historical.':'Elapsed wall-clock time since storage commit.'}/>
          <Health label="OI source freshness" value={isDemo?'Synthetic timestamp':'Unknown'} note={isDemo?'Demo values have generated timestamps.':'The Upstox chain schema supplies no dedicated OI update time.'}/>
          <Health label="Underlying quote timestamp" value={detail?.snapshot.spot_feed_at?dateTime(detail.snapshot.spot_feed_at):'Unavailable'} note="Provider feed time; not proof of a fresh trade or per-field update."/>
        </div>
        <section className="panel"><div className="panel-heading"><h2>Observation quality</h2></div>
          <div className="health-body"><p><b>Provider:</b> {state.config.provider} · <b>Underlying:</b> {state.config.underlying}</p>
            <p><b>Last collector error:</b> {state.worker.last_error || 'None reported'}</p>
            <p><b>Heartbeat age:</b> {number(state.worker.heartbeat_age_seconds,1)} seconds</p>
            <p><b>Collection limit:</b> {state.config.max_collection_seconds}s · <b>Quote age limit:</b> {state.config.max_quote_age_seconds}s</p>
            <p><b>Latest warnings:</b> {latest?.evaluation.warnings.map(words).join(' · ') || 'No observations'}</p>
            <p><b>Session calendar:</b> Weekday hours only in this release. Exchange holidays and special sessions are pending.</p>
            <p><b>Execution:</b> Disabled. Research observations cannot place orders.</p></div>
        </section>
      </>}
      {tab==='Configuration' && <section className="panel">
        <div className="panel-heading"><div><h2>Research parameters</h2><p>Saving creates and activates a new version. Previous recordings remain available through the API.</p></div><span className="pill">ACTIVE v{state.config_id}</span></div>
        <form onSubmit={e=>{e.preventDefault(); void save()}}>
          <div className="form-grid">
            <label>Configuration name<input required maxLength={80} value={draft.name} onChange={e=>setDraft({...draft,name:e.target.value})}/></label>
            <label>Data gateway<select value={draft.provider} onChange={e=>setDraft({...draft,provider:e.target.value as Config['provider']})}><option value="demo">Synthetic demo</option><option value="upstox">Upstox · real market data</option></select></label>
            <label>Underlying instrument key<input required value={draft.underlying} onChange={e=>setDraft({...draft,underlying:e.target.value})}/></label>
            <label>Explicit expiry date<input required type="date" value={draft.expiry} onChange={e=>setDraft({...draft,expiry:e.target.value})}/></label>
            <label>Morning anchor · IST<input required type="time" min="09:15" max="15:29" value={draft.anchor_time} onChange={e=>setDraft({...draft,anchor_time:e.target.value})}/></label>
            {([['wings','Strikes on each side of ATM'],['interval_seconds','Observation interval · seconds'],['anchor_tolerance_seconds','Morning capture tolerance · seconds'],['max_quote_age_seconds','Maximum quote age · seconds'],['max_collection_seconds','Maximum collection duration · seconds']] as const).map(([key,label])=>
              <label key={key}>{label}<input type="number" required min={schema[key]?.minimum} max={schema[key]?.maximum} value={draft[key]} onChange={e=>setDraft({...draft,[key]:Number(e.target.value)})}/></label>)}
          </div>
          <div className="form-notes"><p>Both ATM modes always run. The nearest listed strike defines ATM; an exact midpoint selects the lower strike. The default ±5 and 09:20 are editable research settings.</p>
            <p>A new version starts with a new anchor history. For Upstox, activating after the morning tolerance has elapsed produces a missed anchor for that session.</p>
            {draft.provider==='upstox' && <p>Set your token in the local backend environment and restart the worker. Choose a listed expiry; this form does not discover expiries yet.</p>}</div>
          <div className="form-actions"><span>{state.enabled?'Pause collection to save a new version.':'Collection is paused. Ready to version changes.'}</span><button type="button" onClick={()=>setDraft(state.config)}>Reset edits</button><button className="primary" disabled={busy||state.enabled} type="submit">Save & activate version</button></div>
        </form>
      </section>}
      <footer><span>MARKET STRATEGY LAB / v0.1</span><span>All session times shown in IST · Research only</span></footer>
    </main>
  </div>
}
function Health({label,value,note}:{label:string;value:string;note:string}) {
  return <article className="panel health-card"><div className="eyebrow">{label}</div><h2>{value}</h2><p>{note}</p></article>
}

const positioningLabels:Record<PositioningClassification,string> = {LONG_BUILDUP:'LB',SHORT_BUILDUP:'SB',LONG_UNWINDING:'LW',SHORT_COVERING:'SC',NEUTRAL:'N',UNAVAILABLE:'—'}

type OiDirectionalStatus = 'BULLISH'|'BEARISH'|'MIXED'|'UNAVAILABLE'

const oiDirectionalStatus = (
  ce?: StrikePositioningResult,
  pe?: StrikePositioningResult,
): OiDirectionalStatus => {
  const ceState = ce?.classification
  const peState = pe?.classification

  if (
    !ceState || !peState ||
    ceState === 'UNAVAILABLE' ||
    peState === 'UNAVAILABLE'
  ) return 'UNAVAILABLE'

  if (
    ceState === 'LONG_BUILDUP' &&
    peState === 'SHORT_BUILDUP'
  ) return 'BULLISH'

  if (
    ceState === 'SHORT_BUILDUP' &&
    peState === 'LONG_BUILDUP'
  ) return 'BEARISH'

  return 'MIXED'
}

const oiDirectionalBadge = (
  ce?: StrikePositioningResult,
  pe?: StrikePositioningResult,
) => {
  const status = oiDirectionalStatus(ce, pe)
  const label = status === 'UNAVAILABLE' ? '—' : status

  return (
    <span className={`oi-direction ${status.toLowerCase()}`}>
      {label}
    </span>
  )
}

function StrikePositioning({records,status,view,horizon,movingAtm,fixedAtm,onView,onHorizon}:{
  records:StrikePositioningResult[]; status:'loading'|'refreshing'|'ready'|'error'; view:'moving'|'fixed'|'full'; horizon:PositioningHorizon
  movingAtm:number|null; fixedAtm:number|null; onView:(v:'moving'|'fixed'|'full')=>void; onHorizon:(h:PositioningHorizon)=>void
}) {
  const valid=(v:number|null|undefined)=>typeof v==='number'&&Number.isFinite(v)?v:null
  const value=(v:number|null|undefined)=>valid(v)==null?'—':valid(v)!.toLocaleString('en-IN',{maximumFractionDigits:2})
  const percent=(v:number|null|undefined)=>valid(v)==null?'—':`${valid(v)!>0?'+':''}${valid(v)!.toFixed(2)}%`
  const positionState=(r?:StrikePositioningResult)=>{const c=r?.classification??'UNAVAILABLE';return <span className="position-state" title={words(c)}>{positioningLabels[c]}</span>}
  const pairs=new Map<number,{CE?:StrikePositioningResult;PE?:StrikePositioningResult}>()
  records.forEach(r=>{const pair=pairs.get(r.strike)??{};pair[r.side]=r;pairs.set(r.strike,pair)})
  const all=[...pairs.keys()].sort((a,b)=>a-b), atm=view==='fixed'?fixedAtm:movingAtm
  const index=atm==null?-1:all.indexOf(atm)
  const strikes=view==='full'?all:index<0?[]:all.slice(Math.max(0,index-5),index+6)
  return <section className="panel positioning-panel">
    <div className="panel-heading positioning-heading"><div><h2>Strike Positioning</h2><p>Per-contract option price and observed OI changes</p></div></div>
    <div className="positioning-controls"><div className="segmented">
      {([['moving','Moving ATM ±5'],['fixed','Fixed ATM ±5'],['full','Full Chain']] as const).map(([k,label])=><button key={k} className={view===k?'active':''} onClick={()=>onView(k)}>{label}</button>)}
    </div><div className="segmented compact">
      {([[300,'5m'],[900,'15m'],[1800,'30m']] as const).map(([h,label])=><button key={h} className={horizon===h?'active':''} onClick={()=>onHorizon(h)}>{label}</button>)}
    </div></div>
    {status==='loading'&&!records.length?<div className="positioning-message">Strike Positioning loading...</div>:status==='error'&&!records.length?<div className="positioning-message">Strike Positioning unavailable</div>:
      view==='fixed'&&fixedAtm==null?<div className="positioning-message">Fixed Morning ATM unavailable for this session.</div>:!strikes.length?<div className="positioning-message">No positioning data available</div>:
      <div className={'positioning-table-scroll '+(view==='full'?'full':'')}><table className="positioning-table"><thead>
        <tr className="positioning-sides"><th colSpan={4}>CALL</th><th>STRIKE</th><th>OI STATUS</th><th colSpan={4}>PUT</th></tr>
        <tr><th>LTP</th><th>ΔP%</th><th>ΔOI%</th><th>State</th><th>Strike</th><th>State</th><th>ΔOI%</th><th>ΔP%</th><th>LTP</th></tr>
      </thead><tbody>{strikes.map(strike=>{const pair=pairs.get(strike)??{},isAtm=atm===strike;return <tr key={strike} className={isAtm?'positioning-atm':''}>
        <td>{value(pair.CE?.current_ltp)}</td><td>{percent(pair.CE?.price_change_pct)}</td><td>{percent(pair.CE?.observed_oi_change_pct)}</td><td>{positionState(pair.CE)}</td>
        <th scope="row">{number(strike)}{isAtm&&<small>ATM</small>}</th>
        <td>{oiDirectionalBadge(pair.CE,pair.PE)}</td><td>{positionState(pair.PE)}</td><td>{percent(pair.PE?.observed_oi_change_pct)}</td><td>{percent(pair.PE?.price_change_pct)}</td><td>{value(pair.PE?.current_ltp)}</td>
      </tr>})}</tbody></table></div>}
    <div className="panel-foot">LB Long Buildup · SB Short Buildup · LW Long Unwinding · SC Short Covering · N Neutral</div>
  </section>
}


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

function OISection({detail,result}:{detail:Detail;result:Result}) {
  const quote = (strike:number, side:'CE'|'PE') => {
    const contract=detail.snapshot.catalog.find(c=>c.strike===strike&&c.side===side)
    return detail.snapshot.quotes.find(q=>q.key===contract?.key)
  }
  const change = (current:number|null|undefined, previous:number|null|undefined) =>
    current == null || previous == null ? null : current - previous
  const percent = (current:number|null|undefined, previous:number|null|undefined) =>
    current == null || previous == null || previous === 0 ? null : (current-previous)/previous*100
  return <section className={'oi-section '+result.mode}>
    <div className="oi-heading"><div><h2>{titles[result.mode]}</h2><p>{result.mode==='full'?'All paired catalog strikes':`ATM ${number(result.atm)} / ${result.strikes.length} strikes`} / {result.received}/{result.expected} contracts</p></div><strong>{result.pcr?.toFixed(3) ?? '—'} <small>PCR</small></strong></div>
    <div className="table-scroll"><table><thead><tr><th>Strike</th><th>Call OI</th><th>Call ΔOI</th><th>Call Δ%</th><th>Put OI</th><th>Put ΔOI</th><th>Put Δ%</th><th>Strike PCR</th></tr></thead><tbody>
      {result.strikes.map(strike=>{const call=quote(strike,'CE'), put=quote(strike,'PE'); const strikePcr=call?.oi&&put?.oi!=null?put.oi/call.oi:null; return <tr key={strike}><td>{number(strike)}</td><td>{number(call?.oi)}</td><td>{signed(change(call?.oi,call?.prev_oi))}</td><td>{signed(percent(call?.oi,call?.prev_oi),2)}{percent(call?.oi,call?.prev_oi)!=null?'%':''}</td><td>{number(put?.oi)}</td><td>{signed(change(put?.oi,put?.prev_oi))}</td><td>{signed(percent(put?.oi,put?.prev_oi),2)}{percent(put?.oi,put?.prev_oi)!=null?'%':''}</td><td>{strikePcr?.toFixed(3)??'—'}</td></tr>})}
    </tbody><tfoot><tr><th>Total</th><th>{number(result.call_oi)}</th><th>{signed(result.call_change_oi)}</th><th>{signed(result.call_change_pct,2)}{result.call_change_pct!=null?'%':''}</th><th>{number(result.put_oi)}</th><th>{signed(result.put_change_oi)}</th><th>{signed(result.put_change_pct,2)}{result.put_change_pct!=null?'%':''}</th><th>{result.pcr?.toFixed(3)??'—'}</th></tr></tfoot></table></div>
    {result.issues.length>0&&<p className="issue oi-issue">{result.issues.map(words).join(' / ')}</p>}
  </section>
}
