const value=(x:any)=>typeof x==='number'&&Number.isFinite(x)?x.toLocaleString('en-IN',{maximumFractionDigits:2}):'—'
export function LiveMarkHeaders(){return <><th>Live LTP / bid</th><th>Live indicative / exit ₹</th><th>Quote freshness</th></>}
export function LiveTradeTotal({trade,find}:{trade:any;find:(trade:any,key:string)=>any}){
  if(trade.status!=='ACTIVE')return null
  const marks=(trade.legs??[]).map((l:any)=>find(trade,l.instrument_key))
  const total=(field:string)=>marks.length>0&&marks.every((q:any)=>typeof q?.[field]==='number')?marks.reduce((sum:number,q:any)=>sum+q[field],0):null
  const valid=marks.filter(Boolean).length
  return <p>Live estimates · {valid}/{marks.length} fresh legs · one-lot LTP P&amp;L ₹{value(total('indicative_one_lot_pnl'))} · best-bid exit estimate ₹{value(total('estimated_exit_one_lot_pnl'))}. Totals require every leg and verified lot metadata; fees excluded.</p>
}
export function LiveMarkCells({mark}:{mark:any}){
  return <>
    <td>{value(mark?.ltp)} / {value(mark?.bid)}<small>LTP / best bid</small></td>
    <td>{value(mark?.indicative_one_lot_pnl)} / {value(mark?.estimated_exit_one_lot_pnl)}<small>One lot estimate · fees excluded</small><small>LTP / bid points: {value(mark?.indicative_points)} / {value(mark?.estimated_exit_points)}</small></td>
    <td>{mark?'LIVE FEED':'STALE / UNAVAILABLE'}<small>{mark?.quote_timestamp?new Date(mark.quote_timestamp).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'Candle mark retained separately'}</small>{mark&&<small>{Math.max(0,(Date.now()-Date.parse(mark.quote_timestamp))/1000).toFixed(1)}s old · feed message time</small>}</td>
  </>
}
