import type {HilegaAudit} from './hilegaDecisionTable'

export type DirectionalCandleOverlayRow={
  strategy_id?:string
  decision_timestamp?:string
  source_bar_timestamp?:string
  event_details?:Array<Record<string,any>>
  wma_gap_checks?:Array<Record<string,any>>
  bar_timestamp:string
  open?:number|null
  high?:number|null
  low?:number|null
  close?:number|null
  volume?:number|null
  rsi9?:number|null
  ema3_rsi?:number|null
  wma21_rsi?:number|null
  previous_wma21_rsi?:number|null
  wma21_slope_change?:number|null
  wma21_slope_required?:boolean
  wma21_slope_pass?:boolean|null
  wma21_slope_direction?:string|null
  wma21_current_candle?:string|null
  wma21_previous_candle?:string|null
  wma21_slope_interval_minutes?:number|null
  bullish_wma21_rising?:boolean|null
  bearish_wma21_falling?:boolean|null
  bullish_wma21_slope_pass?:boolean|null
  bearish_wma21_slope_pass?:boolean|null
  bullish_wma21_slope_rejection?:string|null
  bearish_wma21_slope_rejection?:string|null
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
  const events=list(r.accepted_events).map(x=>x.toUpperCase())

  // Candidate/ARMED direction must come from the candidate evidence itself,
  // not from the current trade owner. Opposite-side ARMED is informational
  // and may coexist while the other side remains ACTIVE.
  if(events.some(x=>x.includes('BEARISH')))return 'BEARISH'
  if(events.some(x=>x.includes('PATH1_ARMED_RSI_CROSS_EMA3_UP')))return 'BULLISH'
  if(a==='ARMED_INFORMATION'){
    if(r.bearish_armed===true)return 'BEARISH'
    if(r.bullish_armed===true)return 'BULLISH'
  }

  if(a.startsWith('BEARISH_'))return 'BEARISH'
  if(a.startsWith('BULLISH_'))return 'BULLISH'

  if(r.bearish_armed===true && r.bullish_armed!==true)return 'BEARISH'
  if(r.bullish_armed===true && r.bearish_armed!==true)return 'BULLISH'

  // Owner determines direction only after candidate-specific evidence has
  // been considered.
  if(r.owner_after==='BEARISH'||r.owner_before==='BEARISH')return 'BEARISH'
  if(r.owner_after==='BULLISH'||r.owner_before==='BULLISH')return 'BULLISH'

  if(String(r.bearish_state??'').includes('BEARISH_ACTIVE'))return 'BEARISH'
  if(String(r.bullish_state??'').includes('BULLISH_ACTIVE'))return 'BULLISH'
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
  const v2Rows=rows.filter(r=>r.strategy_id==='HILEGA_WMA_GAP_V2_LIVE_SHADOW')
  if(v2Rows.length){
    const legacy=overlayDirectionalAuditReports(base,rows.filter(r=>r.strategy_id!=='HILEGA_WMA_GAP_V2_LIVE_SHADOW'))
    const dates=new Set(v2Rows.map(r=>r.bar_timestamp.slice(0,10)))
    const projected:HilegaAudit[]=v2Rows.map(r=>{
      const events=Array.isArray(r.accepted_events)?r.accepted_events:String(r.accepted_events??'').split(',').filter(Boolean)
      const details=r.event_details??[]
      return {checkpoint:r.bar_timestamp,bar:{close:r.close,open:r.open,high:r.high,low:r.low},
        conditions:{wma_gap_checks:r.wma_gap_checks??[]},
        strategy:{strategy_id:r.strategy_id,decision_timestamp:r.decision_timestamp,
          source_bar_timestamp:r.source_bar_timestamp,events_emitted:events,
          directional_action:r.action,state_before:r.owner_before,state_after:r.owner_after,
          owner_before:r.owner_before,owner_after:r.owner_after,
          direction:r.owner_after==='NONE'?r.owner_before:r.owner_after},
        transitions:events.map(event=>{
          const d=details.find(x=>x.event_type===event)??{}
          return {...d,event_type:event,event_time:r.bar_timestamp,
            details:{original_entry_time:d.entry_time,original_entry_price:d.entry_price}}
        })}
    })
    return [...legacy.filter(r=>!dates.has(r.checkpoint.slice(0,10))),...projected].sort((a,b)=>b.checkpoint.localeCompare(a.checkpoint))
  }
  const byMinute=new Map<string,DirectionalCandleOverlayRow>()

  for(const r of rows){
    const k=minuteKey(r.bar_timestamp)
    if(k)byMinute.set(k,r)
  }

  const used=new Set<string>()

  // Read-only presentation evidence:
  // map every directional candle to its immediately preceding
  // directional candle in the same session. This does NOT
  // generate or change strategy signals.
  const previousByMinute=
    new Map<string,DirectionalCandleOverlayRow>()

  const chronological=[
    ...rows
  ].sort(
    (a,b)=>
      String(a.bar_timestamp)
        .localeCompare(
          String(b.bar_timestamp)
        )
  )

  let previous:
    DirectionalCandleOverlayRow
    | null=null

  for(const current of chronological){
    const key=
      minuteKey(
        current.bar_timestamp
      )

    if(!key)
      continue

    if(
      previous
      && String(previous.bar_timestamp).slice(0,10)
        === String(current.bar_timestamp).slice(0,10)
    ){
      previousByMinute.set(
        key,
        previous,
      )
    }

    previous=current
  }

  const applyOverlay=(
    report:HilegaAudit,
    d:DirectionalCandleOverlayRow,
  ):HilegaAudit=>{
    const accepted=list(d.accepted_events)
    const suppressed=list(d.suppressed_events)
    const dir=direction(d)
    const prior=previousByMinute.get(minuteKey(d.bar_timestamp)??'')
    const currentWma=d.wma21_rsi??report.indicators?.wma21_rsi??null
    const previousWma=d.previous_wma21_rsi??prior?.wma21_rsi??report.indicators?.previous_wma21_rsi??null
    const change=currentWma==null||previousWma==null?null:Number(currentWma)-Number(previousWma)
    const v2=Boolean(d.wma21_slope_required??report.conditions?.wma21_slope_required)
    const slopePass=change==null||dir==null?null:dir==='BEARISH'?change<0:change>0

    const selectedRoute=
      relation(accepted)
      ?? report.strategy?.selected_route
      ?? null

    const transitions=accepted.map(event=>({
      event_type:event,
      event_time:report.checkpoint,
      source:event,
      price:d.close??report.bar?.close??null,
      entry_price:event.startsWith('ENTRY_')
        ? (d.close??report.bar?.close??null)
        : null,
      exit_reason:event.includes('EXIT')
        ? event
        : null,
      details:{
        directional_overlay:true,
        direction:dir,
      },
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
        ema3_rsi:
          d.ema3_rsi
          ?? report.indicators?.ema3_rsi
          ?? null,
        wma21_rsi:
          d.wma21_rsi
          ?? report.indicators?.wma21_rsi
          ?? null,
      },

      conditions:{
        ...(report.conditions??{}),
        wma21_slope_change:change,
        wma21_slope_direction:change==null?'UNAVAILABLE':change>0?'RISING':change<0?'FALLING':'FLAT',
        wma21_slope_required:v2,
        wma21_slope_pass:v2?slopePass:null,
        wma21_slope_gate_status:v2?(slopePass?'PASS':slopePass===false?'FAIL':'UNAVAILABLE'):'INFORMATIONAL_ONLY',
        bullish_wma21_rising:change==null?null:change>0,
        bearish_wma21_falling:change==null?null:change<0,
        wma21_current_candle:d.bar_timestamp,
        wma21_previous_candle:d.wma21_previous_candle??prior?.bar_timestamp??null,
        wma21_slope_interval_minutes:d.wma21_slope_interval_minutes??(prior?Math.round((new Date(d.bar_timestamp).getTime()-new Date(prior.bar_timestamp).getTime())/60000):null),
      },

      strategy:{
        ...(report.strategy??{}),

        state_after:
          stateAfter(d,dir),

        selected_route:
          selectedRoute,

        events_emitted:
          accepted,

        direction:
          dir,

        directional_action:
          d.action??null,

        owner_before:
          d.owner_before??null,

        owner_after:
          d.owner_after??null,

        bullish_state:
          d.bullish_state??null,

        bearish_state:
          d.bearish_state??null,

        bullish_armed:
          d.bullish_armed??null,

        bearish_armed:
          d.bearish_armed??null,

        suppressed_events:
          suppressed,

        directional_note:
          d.note??null,
      },

      transitions,
    }
  }


  // First preserve every existing canonical Hilega audit row.
  const merged:HilegaAudit[]=base.map(report=>{
    const key=minuteKey(report.checkpoint)

    if(!key)
      return report

    const d=byMinute.get(key)

    if(!d)
      return report

    used.add(key)

    return applyOverlay(
      report,
      d,
    )
  })


  // Then add directional checkpoints that do not exist in
  // the legacy bullish audit. These are what today's live
  // directional session needs.
  for(const d of rows){
    const key=minuteKey(
      d.bar_timestamp
    )

    if(!key || used.has(key))
      continue

    used.add(key)

    const accepted=
      list(d.accepted_events)

    const dir=
      direction(d)
    const prior=previousByMinute.get(minuteKey(d.bar_timestamp)??'')
    const currentWma=d.wma21_rsi??null
    const previousWma=d.previous_wma21_rsi??prior?.wma21_rsi??null
    const slopeChange=currentWma==null||previousWma==null?null:Number(currentWma)-Number(previousWma)
    const slopePass=slopeChange==null||dir==null?null:dir==='BEARISH'?slopeChange<0:slopeChange>0
    const v2=Boolean(d.wma21_slope_required)

    const synthetic={
      checkpoint:
        d.bar_timestamp,

      mode:
        'LIVE_DIRECTIONAL',

      strategy:{
        state_before:
          d.owner_before
          ?? null,

        state_after:
          stateAfter(d,dir),

        selected_route:
          relation(accepted),

        route_b_suppressed_by_route_a_priority:
          null,

        events_emitted:
          accepted,

        direction:
          dir,

        directional_action:
          d.action??null,

        owner_before:
          d.owner_before??null,

        owner_after:
          d.owner_after??null,

        bullish_state:
          d.bullish_state??null,

        bearish_state:
          d.bearish_state??null,

        bullish_armed:
          d.bullish_armed??null,

        bearish_armed:
          d.bearish_armed??null,

        suppressed_events:
          list(d.suppressed_events),

        directional_note:
          d.note??null,
      },

      bar:{
        open:
          d.open??null,

        high:
          d.high??null,

        low:
          d.low??null,

        close:
          d.close??null,

        volume:
          d.volume??null,
      },

      indicators:{
        rsi9:
          d.rsi9??null,

        ema3_rsi:
          d.ema3_rsi??null,

        wma21_rsi:
          d.wma21_rsi??null,

        previous_rsi9:
          previousByMinute
            .get(key)
            ?.rsi9
          ?? null,

        previous_ema3_rsi:
          previousByMinute
            .get(key)
            ?.ema3_rsi
          ?? null,

        previous_wma21_rsi:
          previousByMinute
            .get(key)
            ?.wma21_rsi
          ?? null,
      },

      conditions:{
        wma21_slope_change:slopeChange,
        wma21_slope_direction:slopeChange==null?'UNAVAILABLE':slopeChange>0?'RISING':slopeChange<0?'FALLING':'FLAT',
        wma21_slope_required:v2,
        wma21_slope_gate_status:v2?(slopePass?'PASS':slopePass===false?'FAIL':'UNAVAILABLE'):'INFORMATIONAL_ONLY',
        wma21_slope_pass:v2?slopePass:null,
        bullish_wma21_rising:slopeChange==null?null:slopeChange>0,
        bearish_wma21_falling:slopeChange==null?null:slopeChange<0,
        bullish_wma21_slope_rejection:d.bullish_wma21_slope_rejection??null,
        bearish_wma21_slope_rejection:d.bearish_wma21_slope_rejection??null,
        wma21_current_candle:d.bar_timestamp,
        wma21_previous_candle:d.wma21_previous_candle??prior?.bar_timestamp??null,
        wma21_slope_interval_minutes:d.wma21_slope_interval_minutes??(prior?Math.round((new Date(d.bar_timestamp).getTime()-new Date(prior.bar_timestamp).getTime())/60000):null),
      },

      route_a:{
        eligible:null,
        pass:null,
        fail_reasons:[],
      },

      route_b:{
        eligible:null,
        pass:null,
        fail_reasons:[],
      },

      transitions:
        accepted.map(event=>({
          event_type:event,
          event_time:
            d.bar_timestamp,
          source:event,
          price:
            d.close??null,
          entry_price:
            event.startsWith('ENTRY_')
              ? d.close??null
              : null,
          exit_reason:
            event.includes('EXIT')
              ? event
              : null,
          details:{
            directional_overlay:true,
            directional_only:true,
            direction:dir,
          },
        })),

      option_candidate:null,

      option_market_snapshot:null,

      option_lifecycle:{
        start:null,
        updates:[],
        exit:null,
      },

      audit_integrity:{
        chain_ok:null,
        chain_issue:null,
        records:[],
      },

      safety:{
        observation_only:true,
        execution_enabled:false,
        paper_order_enabled:false,
      },
    } as unknown as HilegaAudit

    merged.push(
      synthetic
    )
  }


  // Existing Hilega screen convention expects latest
  // checkpoints first.
  return merged.sort(
    (a,b)=>
      String(b.checkpoint)
        .localeCompare(
          String(a.checkpoint)
        )
  )
}
