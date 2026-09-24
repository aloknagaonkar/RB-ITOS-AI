import {useEffect,useMemo,useState} from 'react'

export type DirectionalCandleRow={
  session_date:string
  time:string|null
  bar_timestamp:string
  open:number|null
  high:number|null
  low:number|null
  close:number|null
  volume:number|null
  rsi9:number|null
  ema3_rsi:number|null
  wma21_rsi:number|null
  owner_before:string|null
  owner_after:string|null
  bullish_state:string|null
  bearish_state:string|null
  bullish_armed:boolean|null
  bearish_armed:boolean|null
  action:string
  accepted_events:string
  suppressed_events:string
  note:string|null
  directional_evidence?:boolean
}

type Feed={
  mode:string
  session_date:string|null
  row_count:number
  directional_row_count:number
  rows:DirectionalCandleRow[]
  warning:string
}

const n=(v:any,d=2)=>v==null?'—':Number(v).toLocaleString('en-IN',{maximumFractionDigits:d})
const words=(v:any)=>v==null?'—':String(v).replaceAll('_',' ')
const eventText=(v:any)=>!v?'—':String(v).split(',').join(' · ')

function rowClass(r:DirectionalCandleRow){
  const a=String(r.action||'').toUpperCase()
  if(a.includes('ENTRY'))return 'hilega-row-entry'
  if(a.includes('EXIT'))return 'hilega-row-exit'
  if(a.includes('ARMED'))return 'hilega-row-detected'
  return ''
}

export default function HilegaDirectionalCandleTable(
  {mode,sessionDate}:{mode:'LIVE'|'HISTORICAL';sessionDate?:string}
){
  const [feed,setFeed]=useState<Feed|null>(null)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)

  useEffect(()=>{
    let active=true
    const run=async()=>{
      setBusy(true);setError('')
      try{
        if(mode==='HISTORICAL'&&!sessionDate){setFeed(null);return}
        const url=mode==='LIVE'
          ? '/api/live-shadow/hilega-directional-candles/live'
          : `/api/live-shadow/hilega-directional-candles/historical?session_date=${encodeURIComponent(sessionDate??'')}`
        const r=await fetch(url)
        if(!r.ok)throw new Error(`Directional candles HTTP ${r.status}: ${await r.text()}`)
        const body=await r.json() as Feed
        if(active)setFeed(body)
      }catch(e){if(active){setFeed(null);setError(String(e))}}
      finally{if(active)setBusy(false)}
    }
    void run()
    const id=mode==='LIVE'?window.setInterval(()=>void run(),15000):undefined
    return()=>{active=false;if(id)window.clearInterval(id)}
  },[mode,sessionDate])

  const rows=useMemo(()=>feed?.rows??[],[feed])

  if(busy&&!feed)return <div className="empty">Loading directional candle audit…</div>
  if(error)return <div className="banner error">{error}</div>
  if(!feed||!rows.length)return <div className="empty">No completed directional candle rows available yet.</div>

  return <>
    <div className="hilega-dashboard-warning">{feed.warning}</div>
    <div className="shadow-table-scroll">
      <table className="shadow-table hilega-economics-table">
        <thead><tr>
          <th>Time</th><th>NIFTY O</th><th>H</th><th>L</th><th>C</th>
          <th>RSI9</th><th>EMA3 RSI</th><th>WMA21 RSI</th>
          <th>Owner</th><th>Bullish state</th><th>Bearish state</th>
          <th>Action</th><th>Accepted</th><th>Suppressed</th>
        </tr></thead>
        <tbody>{rows.map((r,i)=><tr key={`${r.bar_timestamp}-${i}`} className={rowClass(r)}>
          <td><b>{r.time??'—'}</b>{r.directional_evidence===false&&<small> · candle only</small>}</td>
          <td>{n(r.open)}</td><td>{n(r.high)}</td><td>{n(r.low)}</td><td>{n(r.close)}</td>
          <td>{n(r.rsi9)}</td><td>{n(r.ema3_rsi)}</td><td>{n(r.wma21_rsi)}</td>
          <td>{words(r.owner_after)}</td>
          <td>{words(r.bullish_state)}{r.bullish_armed===true?' · ARMED':''}</td>
          <td>{words(r.bearish_state)}{r.bearish_armed===true?' · ARMED':''}</td>
          <td><b>{words(r.action)}</b></td>
          <td>{eventText(r.accepted_events)}</td>
          <td>{eventText(r.suppressed_events)}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <div className="hilega-dashboard-warning">
      {feed.row_count} candle rows · {feed.directional_row_count} with directional-state evidence
      {feed.session_date?` · ${feed.session_date}`:''}
    </div>
  </>
}
