import type {HilegaAudit} from './hilegaDecisionTable'

export type DirectionalCandleOverlayRow={
  bar_timestamp:string
  open?:number|null
  high?:number|null
  low?:number|null
  close?:number|null
  volume?:number|null
  rsi9?:number|null
  ema3_rsi?:number|null
  wma21_rsi?:number|null
  owner_before?:string|null
  owner_after?:string|null
  bullish_state?:string|null
  bearish_state?:string|null
  bullish_armed?:boolean|null
  bearish_armed?:boolean|null
  action?:string|null
  accepted_events?:string|string[]
  suppressed_events?:string|string[]
  note?:string|null
}

export type DirectionalTradeOverlay={
  direction?:string|null
  signal_bar?:string|null
  source?:string|null
  exit_reason?:string|null
  status?:string|null
  legs?:Array<{
    exit_timestamp?:string|null
  }>
}

const list=(v:unknown):string[]=>{
  if(Array.isArray(v))return v.map(String).filter(Boolean)
  if(v==null||v==='')return []
  return String(v).split(',').map(x=>x.trim()).filter(Boolean)
}

const minuteKey=(v:unknown):string|null=>{
  if(!v)return null
  const d=new Date(String(v))
  if(Number.isNaN(d.getTime()))return String(v).slice(0,16)
  // Absolute epoch-minute key avoids +05:30 / Z / seconds formatting mismatches.
  return String(Math.floor(d.getTime()/60000))
}

const addEvent=(row:DirectionalCandleOverlayRow,event:string)=>{
  const events=list(row.accepted_events)
  if(!events.includes(event))events.push(event)
  row.accepted_events=events
}

const relation=(events:string[]):string|null=>{
  const s=events.join('|')
  if(s.includes('ROUTE_A'))return 'ROUTE_A'
  if(s.includes('ROUTE_B'))return 'ROUTE_B'
  if(s.includes('OPENING'))return 'OPENING_PATH'
  return null
}

const direction=(r:DirectionalCandleOverlayRow):'BULLISH'|'BEARISH'|null=>{
  const a=String(r.action??'').toUpperCase()
  if(a.startsWith('BEARISH_'))return 'BEARISH'
  if(a.startsWith('BULLISH_'))return 'BULLISH'
  if(r.owner_after==='BEARISH'||r.owner_before==='BEARISH')return 'BEARISH'
  if(r.owner_after==='BULLISH'||r.owner_before==='BULLISH')return 'BULLISH'
  const events=list(r.accepted_events).map(x=>x.toUpperCase())
  if(events.some(x=>x.includes('BEARISH')))return 'BEARISH'
  if(events.some(x=>x.startsWith('ENTRY_')||x.includes('RSI_CROSS_BELOW_WMA21')))return 'BULLISH'
  if(r.bearish_armed===true||String(r.bearish_state??'').includes('BEARISH_ACTIVE'))return 'BEARISH'
  if(r.bullish_armed===true||String(r.bullish_state??'').includes('BULLISH_ACTIVE'))return 'BULLISH'
  return null
}

const stateAfter=(r:DirectionalCandleOverlayRow,d:'BULLISH'|'BEARISH'|null):string|null=>{
  if(r.owner_after==='BULLISH')return 'BULLISH_ACTIVE'
  if(r.owner_after==='BEARISH')return 'BEARISH_ACTIVE'
  if(d==='BEARISH')return r.bearish_state??null
  if(d==='BULLISH')return r.bullish_state??null
  if(r.bearish_armed===true)return r.bearish_state??'BEARISH_PATH1_ARMED'
  if(r.bullish_armed===true)return r.bullish_state??'PATH1_ARMED'
  return r.bullish_state??r.bearish_state??null
}

export function augmentDirectionalRowsWithTrades(
  rows:DirectionalCandleOverlayRow[],
  trades:DirectionalTradeOverlay[],
):DirectionalCandleOverlayRow[]{
  const out=rows.map(r=>({...r}))
  const byMinute=new Map<string,DirectionalCandleOverlayRow>()
  for(const row of out){
    const k=minuteKey(row.bar_timestamp)
    if(k)byMinute.set(k,row)
  }

  const ensure=(timestamp:string):DirectionalCandleOverlayRow=>{
    const k=minuteKey(timestamp)!
    const existing=byMinute.get(k)
    if(existing)return existing
    const created:DirectionalCandleOverlayRow={
      bar_timestamp:timestamp,
      action:'NO_ACTION',
      accepted_events:[],
      suppressed_events:[],
    }
    byMinute.set(k,created)
    out.push(created)
    return created
  }

  for(const trade of trades??[]){
    const dir=String(trade.direction??'').toUpperCase()
    const signal=trade.signal_bar
    if((dir==='BULLISH'||dir==='BEARISH')&&signal){
      const row=ensure(signal)
      const event=String(trade.source??'').trim()
      if(event)addEvent(row,event)
      row.action=`${dir}_ENTRY`
      row.owner_before=row.owner_before??'NONE'
      row.owner_after=dir
      if(dir==='BULLISH'){
        row.bullish_state='BULLISH_ACTIVE'
        row.bullish_armed=false
      }else{
        row.bearish_state='BEARISH_ACTIVE'
        row.bearish_armed=false
      }
      row.note=[row.note,'ENTRY_RECOVERED_FROM_DIRECTIONAL_TRADE_DASHBOARD'].filter(Boolean).join('; ')
    }

    const reason=String(trade.exit_reason??'').trim()
    const rawExit=trade.legs?.map(x=>x.exit_timestamp).find(Boolean)??null
    if((dir==='BULLISH'||dir==='BEARISH')&&reason&&rawExit){
      const exitBoundary=new Date(String(rawExit))
      if(!Number.isNaN(exitBoundary.getTime())){
        // Structural option exit is the following 5m OPEN. Cutoff exit is 14:55 OPEN itself.
        const signalMs=reason.endsWith('SESSION_CUTOFF_EXIT_1455_OPEN')
          ? exitBoundary.getTime()
          : exitBoundary.getTime()-5*60_000
        const exitSignal=new Date(signalMs).toISOString()
        const row=ensure(exitSignal)
        addEvent(row,reason)
        row.action=`${dir}_EXIT`
        row.owner_before=dir
        row.owner_after='NONE'
        if(dir==='BULLISH'){
          row.bullish_state=row.bullish_state??'PATH1_IDLE'
          row.bullish_armed=false
        }else{
          row.bearish_state=row.bearish_state??'BEARISH_PATH1_IDLE'
          row.bearish_armed=false
        }
        row.note=[row.note,'EXIT_RECOVERED_FROM_DIRECTIONAL_TRADE_DASHBOARD'].filter(Boolean).join('; ')
      }
    }
  }

  return out.sort((a,b)=>String(a.bar_timestamp).localeCompare(String(b.bar_timestamp)))
}

export function overlayDirectionalAuditReports(
  base:HilegaAudit[],
  rows:DirectionalCandleOverlayRow[],
):HilegaAudit[]{
  const byMinute=new Map<string,DirectionalCandleOverlayRow>()
  for(const r of rows){
    const k=minuteKey(r.bar_timestamp)
    if(k)byMinute.set(k,r)
  }

  return base.map(report=>{
    const key=minuteKey(report.checkpoint)
    const d=key?byMinute.get(key):undefined
    if(!d)return report

    const accepted=list(d.accepted_events)
    const suppressed=list(d.suppressed_events)
    const dir=direction(d)
    const selectedRoute=relation(accepted)??report.strategy?.selected_route??null

    const transitions=accepted.map(event=>({
      event_type:event,
      event_time:report.checkpoint,
      source:event,
      price:d.close??report.bar?.close??null,
      entry_price:event.startsWith('ENTRY_')?(d.close??report.bar?.close??null):null,
      exit_reason:event.includes('EXIT')?event:null,
      details:{directional_overlay:true,direction:dir},
    }))

    return {
      ...report,
      bar:{
        ...(report.bar??{}),
        open:d.open??report.bar?.open??null,
        high:d.high??report.bar?.high??null,
        low:d.low??report.bar?.low??null,
        close:d.close??report.bar?.close??null,
        volume:d.volume??report.bar?.volume??null,
      },
      indicators:{
        ...(report.indicators??{}),
        rsi9:d.rsi9??report.indicators?.rsi9??null,
        ema3_rsi:d.ema3_rsi??report.indicators?.ema3_rsi??null,
        wma21_rsi:d.wma21_rsi??report.indicators?.wma21_rsi??null,
      },
      strategy:{
        ...(report.strategy??{}),
        state_after:stateAfter(d,dir),
        selected_route:selectedRoute,
        events_emitted:accepted,
        direction:dir,
        directional_action:d.action??null,
        owner_before:d.owner_before??null,
        owner_after:d.owner_after??null,
        bullish_state:d.bullish_state??null,
        bearish_state:d.bearish_state??null,
        bullish_armed:d.bullish_armed??null,
        bearish_armed:d.bearish_armed??null,
        suppressed_events:suppressed,
        directional_note:d.note??null,
      },
      transitions,
    }
  })
}
