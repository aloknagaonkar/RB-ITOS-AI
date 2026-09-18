from pathlib import Path

tsx = Path("frontend/src/historicalReplay.tsx")
css = Path("frontend/src/historicalReplay.css")

text = tsx.read_text(encoding="utf-8")

start = text.find("function CheckpointDetail(")
end = text.find("\nexport default function HistoricalReplay", start)

if start < 0 or end < 0:
    raise SystemExit(
        "SAFE STOP: could not locate CheckpointDetail block in "
        "frontend/src/historicalReplay.tsx"
    )

replacement = r'''
type ProgressItem = {
  timestamp:string
  source:'AUDIT'|'EVENT'
  stage:string
  status:string
  observation_id:string
  detail:string
  payload:Record<string,any>
  sort_order:number
}

const eventOrder:Record<string,number> = {
  OBSERVATION_DETECTED:10,
  CANDLE2_CONFIRMED:20,
  FUTURES_ALIGNMENT_CHECKED:30,
  SPOT_LAG_CLASSIFIED:40,
  OPTION_RESOLVED:50,
  ENTRY_OPEN:60,
  ENTRY_OPENED:61,
  OPTION_MINUTE_HEALTH:70,
  OPTION_MINUTE:71,
  RISK_STATE_UPDATED:72,
  TRADE_CLOSED:90,
}

function firstValue(payload:Record<string,any>, keys:string[]){
  for(const key of keys){
    const value=payload?.[key]
    if(value!==undefined && value!==null && value!=='') return value
  }
  return null
}

function pct(value:any){
  if(value===undefined || value===null || value==='') return null
  const num=Number(value)
  if(Number.isNaN(num)) return String(value)
  return `${num>=0?'+':''}${num.toFixed(2)}%`
}

function money(value:any){
  if(value===undefined || value===null || value==='') return null
  const num=Number(value)
  return Number.isNaN(num) ? String(value) : num.toFixed(2)
}

function eventDetail(stage:string,payload:Record<string,any>){
  const p=payload||{}
  const parts:string[]=[]

  if(stage==='OBSERVATION_DETECTED'){
    const direction=firstValue(p,['direction','target_direction'])
    if(direction) parts.push(String(direction))
  }

  if(stage==='CANDLE2_CONFIRMED'){
    const spot=firstValue(p,['spot','spot_c2','candle2_spot'])
    if(spot!=null) parts.push(`spot ${money(spot)}`)
  }

  if(stage==='FUTURES_ALIGNMENT_CHECKED'){
    const state=firstValue(p,['futures_oi_state','state'])
    const aligned=firstValue(p,['aligned','is_aligned'])
    if(state) parts.push(String(state))
    if(aligned!==null) parts.push(`aligned ${aligned?'YES':'NO'}`)
  }

  if(stage==='SPOT_LAG_CLASSIFIED'){
    const classification=firstValue(p,['classification','spot_classification','spot_class'])
    if(classification) parts.push(String(classification))
  }

  if(stage==='OPTION_RESOLVED'){
    const atm=firstValue(p,['atm_strike','moving_atm','strike'])
    const side=firstValue(p,['option_side','side'])
    const key=firstValue(p,['option_instrument_key','instrument_key'])
    if(atm!=null || side) parts.push(`${atm??''} ${side??''}`.trim())
    if(key) parts.push(String(key))
  }

  if(stage==='ENTRY_OPEN' || stage==='ENTRY_OPENED'){
    const price=firstValue(p,['entry_price','price','open'])
    const key=firstValue(p,['option_instrument_key','instrument_key'])
    if(price!=null) parts.push(`entry ${money(price)}`)
    if(key) parts.push(String(key))
  }

  if(stage==='OPTION_MINUTE'){
    const o=firstValue(p,['open'])
    const h=firstValue(p,['high'])
    const l=firstValue(p,['low'])
    const c=firstValue(p,['close'])
    if([o,h,l,c].some(v=>v!=null)){
      parts.push(`O ${money(o)} H ${money(h)} L ${money(l)} C ${money(c)}`)
    }
  }

  if(stage==='OPTION_MINUTE_HEALTH'){
    const reason=firstValue(p,['reason','health_reason'])
    if(reason) parts.push(String(reason))
  }

  if(stage==='RISK_STATE_UPDATED'){
    const stop=firstValue(p,['active_stop','stop_price','stop'])
    const be=firstValue(p,['breakeven_armed','be_armed','breakeven_active'])
    const trail=firstValue(p,['trail_armed','trailing_armed','trail_active'])
    const mfe=firstValue(p,['mfe_pct','mfe_pct_points','mfe'])
    const mae=firstValue(p,['mae_pct','mae_pct_points','mae'])
    if(stop!=null) parts.push(`stop ${money(stop)}`)
    if(be!==null) parts.push(`BE ${be?'ON':'OFF'}`)
    if(trail!==null) parts.push(`trail ${trail?'ON':'OFF'}`)
    if(mfe!=null) parts.push(`MFE ${pct(mfe)}`)
    if(mae!=null) parts.push(`MAE ${pct(mae)}`)
  }

  if(stage==='TRADE_CLOSED'){
    const reason=firstValue(p,['exit_reason','reason'])
    const exit=firstValue(p,['exit_price','price'])
    const gross=firstValue(p,['gross_return_pct','gross_pct','gross_return'])
    const net=firstValue(p,['net_return_pct','net_pct','net_return'])
    const mfe=firstValue(p,['mfe_pct','mfe_pct_points','mfe'])
    const mae=firstValue(p,['mae_pct','mae_pct_points','mae'])
    if(reason) parts.push(String(reason))
    if(exit!=null) parts.push(`exit ${money(exit)}`)
    if(gross!=null) parts.push(`gross ${pct(gross)}`)
    if(net!=null) parts.push(`net ${pct(net)}`)
    if(mfe!=null) parts.push(`MFE ${pct(mfe)}`)
    if(mae!=null) parts.push(`MAE ${pct(mae)}`)
  }

  return parts.join(' · ')
}

function buildProgress(row:TimelineRow):ProgressItem[]{
  const items:ProgressItem[]=[]

  for(const step of row.candidate_steps||[]){
    items.push({
      timestamp:step.event_time || step.checkpoint || row.checkpoint,
      source:'AUDIT',
      stage:step.stage,
      status:step.status||'',
      observation_id:step.observation_id||'',
      detail:eventDetail(step.stage,step.payload||{}),
      payload:step.payload||{},
      sort_order:eventOrder[step.stage]??55,
    })
  }

  for(const [oid,events] of Object.entries(row.observation_events||{})){
    for(const event of events||[]){
      const stage=event.event_type||'EVENT'
      items.push({
        timestamp:event.event_time || event.timestamp || row.checkpoint,
        source:'EVENT',
        stage,
        status:event.state || event.status || '',
        observation_id:oid,
        detail:eventDetail(stage,event.payload||{}),
        payload:event.payload||{},
        sort_order:eventOrder[stage]??56,
      })
    }
  }

  return items.sort((a,b)=>{
    const ta=Date.parse(a.timestamp)
    const tb=Date.parse(b.timestamp)
    if(Number.isFinite(ta) && Number.isFinite(tb) && ta!==tb) return ta-tb
    if(a.timestamp!==b.timestamp) return a.timestamp.localeCompare(b.timestamp)
    if(a.sort_order!==b.sort_order) return a.sort_order-b.sort_order
    return a.source.localeCompare(b.source)
  })
}

function TradeSummary({progress}:{progress:ProgressItem[]}){
  const option=progress.find(x=>x.stage==='OPTION_RESOLVED')
  const entry=[...progress].reverse().find(x=>x.stage==='ENTRY_OPENED' || x.stage==='ENTRY_OPEN')
  const futures=progress.find(x=>x.stage==='FUTURES_ALIGNMENT_CHECKED')
  const spot=progress.find(x=>x.stage==='SPOT_LAG_CLASSIFIED')
  const closed=[...progress].reverse().find(x=>x.stage==='TRADE_CLOSED')

  if(!option && !entry && !futures && !spot && !closed) return null

  const fields:{label:string,value:string|null}[]=[
    {label:'Futures',value:futures?.detail||null},
    {label:'Spot class',value:spot?.detail||null},
    {label:'Option',value:option?.detail||null},
    {label:'Entry',value:entry?.detail||null},
    {label:'Exit',value:closed?.detail||null},
  ]

  return <div className="hr-trade-summary">
    {fields.filter(x=>x.value).map(field=><div key={field.label}>
      <b>{field.label}</b>
      <span>{field.value}</span>
    </div>)}
  </div>
}

function CheckpointDetail({row}:{row:TimelineRow}){
  const f=row.normalized_features?.payload||{}
  const horizons=f.horizons||{}
  const progress=buildProgress(row)

  return <div className="hr-detail">
    <div className="hr-detail-grid">
      <div><b>Spot</b><span>{n(f.spot)}</span></div>
      <div><b>Moving ATM</b><span>{n(f.moving_atm,0)}</span></div>
      <div><b>Health</b><span>{badge(row.data_health?.status)}</span></div>
      <div><b>ALL3</b><span>{badge(row.all3_decision?.status)}</span></div>
      <div><b>Candidate</b><span>{badge(row.candidate_detection?.status)}</span></div>
      <div><b>Exact strikes</b><span>{(f.moving_strikes||[]).join(', ')||'—'}</span></div>
    </div>

    <div className="hr-horizons">
      <Horizon name="5m" data={horizons['5m']}/>
      <Horizon name="10m" data={horizons['10m']}/>
      <Horizon name="15m" data={horizons['15m']}/>
    </div>

    <TradeSummary progress={progress}/>

    <div className="hr-progress-heading">
      <h4>Strategy progression</h4>
      <span>Chronological · audit + lifecycle events</span>
    </div>

    {!progress.length
      ? <div className="hr-empty">No candidate lifecycle at this checkpoint.</div>
      : <div className="hr-lifecycle">
          {progress.map((item,i)=><div className={`hr-life-row hr-life-${item.source.toLowerCase()}`} key={`${item.timestamp}-${item.stage}-${item.source}-${i}`}>
            <span className="hr-life-time">{shortTime(item.timestamp)}</span>
            <b>{item.stage}</b>
            <span className="hr-life-detail">{item.detail || (item.status?String(item.status):'—')}</span>
            <span className="hr-life-status">{item.status?badge(item.status):null}</span>
            <code title={item.observation_id}>{item.observation_id}</code>
          </div>)}
        </div>}
  </div>
}
'''.strip()

text = text[:start] + replacement + text[end:]
tsx.write_text(text, encoding="utf-8")

css_text = css.read_text(encoding="utf-8")
marker = "/* HISTORICAL_REPLAY_AUDIT_READABILITY_V1_1 */"
if marker not in css_text:
    css_text += r'''

/* HISTORICAL_REPLAY_AUDIT_READABILITY_V1_1 */
.hr-trade-summary{
  display:grid;
  grid-template-columns:repeat(5,minmax(150px,1fr));
  gap:8px;
  margin-top:12px;
}
.hr-trade-summary>div{
  border:1px solid var(--border,#e1e3e7);
  border-radius:8px;
  padding:9px 10px;
  display:flex;
  flex-direction:column;
  gap:4px;
  min-width:0;
}
.hr-trade-summary b{
  font-size:11px;
  text-transform:uppercase;
  opacity:.72;
}
.hr-trade-summary span{
  overflow-wrap:anywhere;
}
.hr-progress-heading{
  display:flex;
  align-items:baseline;
  justify-content:space-between;
  gap:12px;
  margin-top:14px;
}
.hr-progress-heading h4{margin:0 0 8px}
.hr-progress-heading span{font-size:11px;opacity:.62}
.hr-life-row{
  grid-template-columns:64px 190px minmax(250px,1fr) 120px minmax(190px,1fr);
  border-bottom:1px dashed var(--border,#344650);
  padding:5px 0;
}
.hr-life-row:last-child{border-bottom:0}
.hr-life-time{font-variant-numeric:tabular-nums}
.hr-life-detail{white-space:normal;overflow-wrap:anywhere}
.hr-life-status{min-width:0}
.hr-life-row code{
  font-size:10px;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
  opacity:.72;
}
@media(max-width:1100px){
  .hr-trade-summary{grid-template-columns:repeat(2,minmax(150px,1fr))}
  .hr-life-row{grid-template-columns:60px 175px minmax(180px,1fr)}
  .hr-life-status,.hr-life-row code{display:none}
}
@media(max-width:700px){
  .hr-trade-summary{grid-template-columns:1fr}
  .hr-life-row{grid-template-columns:54px 1fr}
  .hr-life-detail{grid-column:2}
}
'''
    css.write_text(css_text, encoding="utf-8")

print("Patched Historical Replay audit readability V1.1.")
