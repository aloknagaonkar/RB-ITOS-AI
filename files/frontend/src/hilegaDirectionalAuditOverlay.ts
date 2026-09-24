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

const items=(v:unknown):string[]=>{
  if(Array.isArray(v))return v.map(String).filter(Boolean)
  if(v==null||v==='')return []
  return String(v).split(',').map(x=>x.trim()).filter(Boolean)
}

const routeFromEvents=(events:string[]):string|null=>{
  const s=events.join('|')
  if(s.includes('ROUTE_A'))return 'ROUTE_A'
  if(s.includes('ROUTE_B'))return 'ROUTE_B'
  if(s.includes('OPENING'))return 'OPENING_PATH'
  return null
}

const directionFor=(r:DirectionalCandleOverlayRow):'BULLISH'|'BEARISH'|null=>{
  const action=String(r.action??'').toUpperCase()
  if(action.startsWith('BEARISH_'))return 'BEARISH'
  if(action.startsWith('BULLISH_'))return 'BULLISH'
  if(r.owner_after==='BEARISH'||r.owner_before==='BEARISH')return 'BEARISH'
  if(r.owner_after==='BULLISH'||r.owner_before==='BULLISH')return 'BULLISH'
  if(String(r.bearish_state??'').includes('BEARISH_')&&(r.bearish_armed||String(r.bearish_state).includes('ACTIVE')))return 'BEARISH'
  if(r.bullish_armed||String(r.bullish_state??'').includes('BULLISH_ACTIVE'))return 'BULLISH'
  return null
}

const stateAfter=(r:DirectionalCandleOverlayRow,direction:'BULLISH'|'BEARISH'|null):string|null=>{
  if(r.owner_after==='BULLISH')return 'BULLISH_ACTIVE'
  if(r.owner_after==='BEARISH')return 'BEARISH_ACTIVE'
  if(direction==='BEARISH')return r.bearish_state??null
  if(direction==='BULLISH')return r.bullish_state??null
  if(r.bearish_armed)return r.bearish_state??'BEARISH_PATH1_ARMED'
  if(r.bullish_armed)return r.bullish_state??'PATH1_ARMED'
  return r.bullish_state??r.bearish_state??null
}

export function overlayDirectionalAuditReports(
  base:HilegaAudit[],
  rows:DirectionalCandleOverlayRow[],
):HilegaAudit[]{
  const byTs=new Map(rows.map(r=>[String(r.bar_timestamp),r]))
  return base.map(report=>{
    const d=byTs.get(String(report.checkpoint))
    if(!d)return report

    const accepted=items(d.accepted_events)
    const suppressed=items(d.suppressed_events)
    const direction=directionFor(d)
    const selectedRoute=routeFromEvents(accepted)??report.strategy?.selected_route??null

    const transitions=accepted.map(event=>({
      event_type:event,
      event_time:report.checkpoint,
      source:event,
      price:d.close??report.bar?.close??null,
      entry_price:event.startsWith('ENTRY_')?(d.close??report.bar?.close??null):null,
      exit_reason:event.includes('EXIT')?event:null,
      details:{directional_overlay:true,direction},
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
        state_after:stateAfter(d,direction),
        selected_route:selectedRoute,
        events_emitted:accepted,
        direction,
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
