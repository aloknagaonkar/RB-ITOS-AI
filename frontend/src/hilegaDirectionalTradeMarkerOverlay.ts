import type {HilegaAudit} from './hilegaDecisionTable'

export type DirectionalTradeMarker={
  direction?:string|null
  signal_bar?:string|null
  signal_boundary?:string|null
  source?:string|null
  exit_reason?:string|null
  status?:string|null
  legs?:Array<{
    exit_timestamp?:string|null
  }>
}

const minuteKey=(v:unknown):string|null=>{
  if(!v)return null
  const d=new Date(String(v))
  if(Number.isNaN(d.getTime()))return null
  return String(Math.floor(d.getTime()/60000))
}

const minusMinutes=(v:unknown,m:number):string|null=>{
  if(!v)return null
  const d=new Date(String(v))
  if(Number.isNaN(d.getTime()))return null
  return new Date(d.getTime()-m*60_000).toISOString()
}

const routeFromEvent=(event:string):string|null=>{
  if(event.includes('ROUTE_A'))return 'ROUTE_A'
  if(event.includes('ROUTE_B'))return 'ROUTE_B'
  if(event.includes('OPENING'))return 'OPENING_PATH'
  return null
}

const addUnique=(xs:any[],item:any,key:(x:any)=>string)=>{
  const k=key(item)
  if(!xs.some(x=>key(x)===k))xs.push(item)
}

export function overlayDirectionalTradeMarkers(
  reports:HilegaAudit[],
  trades:DirectionalTradeMarker[],
):HilegaAudit[]{
  const byMinute=new Map<string,number>()
  reports.forEach((r,i)=>{
    const k=minuteKey(r.checkpoint)
    if(k)byMinute.set(k,i)
  })

  const out=reports.map(r=>({
    ...r,
    strategy:{...(r.strategy??{})},
    transitions:[...(r.transitions??[])],
  }))

  const mark=(timestamp:unknown,event:string,direction:'BULLISH'|'BEARISH',kind:'ENTRY'|'EXIT')=>{
    const k=minuteKey(timestamp)
    if(!k)return false
    const idx=byMinute.get(k)
    if(idx===undefined)return false

    const r=out[idx]
    const events=Array.isArray(r.strategy?.events_emitted)
      ? [...r.strategy.events_emitted]
      : []

    if(!events.includes(event))events.push(event)

    r.strategy={
      ...(r.strategy??{}),
      events_emitted:events,
      direction,
      directional_action:`${direction}_${kind}`,
      selected_route:routeFromEvent(event)??r.strategy?.selected_route??null,
      state_after:kind==='ENTRY'
        ? `${direction}_ACTIVE`
        : (direction==='BEARISH'?'BEARISH_PATH1_IDLE':'PATH1_IDLE'),
    }

    addUnique(
      r.transitions as any[],
      {
        event_type:event,
        event_time:r.checkpoint,
        source:event,
        price:r.bar?.close??null,
        entry_price:kind==='ENTRY'?(r.bar?.close??null):null,
        exit_reason:kind==='EXIT'?event:null,
        details:{directional_trade_marker:true,direction},
      },
      x=>`${String(x?.event_type??'')}|${String(x?.event_time??'')}`,
    )
    return true
  }

  for(const trade of trades??[]){
    const direction=String(trade.direction??'').toUpperCase()
    if(direction!=='BULLISH'&&direction!=='BEARISH')continue
    const dir=direction as 'BULLISH'|'BEARISH'

    const entryEvent=String(trade.source??'').trim()
    if(entryEvent){
      // Primary truth is signal_bar. If an older dashboard omits/misformats it,
      // signal_boundary - 5m is the equivalent signal candle.
      const candidates=[
        trade.signal_bar,
        minusMinutes(trade.signal_boundary,5),
      ].filter(Boolean)

      for(const ts of candidates){
        if(mark(ts,entryEvent,dir,'ENTRY'))break
      }
    }

    const exitEvent=String(trade.exit_reason??'').trim()
    const exactOptionExit=trade.legs?.map(x=>x.exit_timestamp).find(Boolean)??null
    if(exitEvent&&exactOptionExit){
      // Structural option exit is acquired at the next 5m boundary OPEN.
      // Cutoff semantics are exact 14:55 OPEN, so no -5m shift there.
      const signalTs=exitEvent.endsWith('SESSION_CUTOFF_EXIT_1455_OPEN')
        ? exactOptionExit
        : minusMinutes(exactOptionExit,5)
      mark(signalTs,exitEvent,dir,'EXIT')
    }
  }

  return out
}
