export function matchSandbox(shadow, sandboxTrades) {
  const times=[shadow.signal_boundary,shadow.signal_bar].filter(Boolean).map(Date.parse)
  const matches=sandboxTrades.filter(t=>t.direction===shadow.direction&&t.expiry===shadow.expiry&&times.includes(Date.parse(t.entry_signal_time)))
  return matches.length===1?matches[0]:null
}
export function strikeRows(shadow, sandbox) {
  return [-2,-1,0,1,2].map(role=>{
    const matches=(shadow.legs??[]).filter(x=>x.relation_to_atm===role)
    const leg=matches.length===1?matches[0]:null
    const selected=!!(leg&&sandbox&&leg.instrument_key===sandbox.instrument_key&&shadow.expiry===sandbox.expiry)
    const entry=leg?.entry_open??null
    const exit=leg?.exit_open??null
    const isClosed=shadow.status==='CLOSED'
    const mark=isClosed?exit:shadow.status==='ACTIVE'?leg?.latest_close??null:null
    const points=entry!=null&&mark!=null?mark-entry:null
    const qty=sandbox?.quantity>0?sandbox.quantity:null
    return {role,leg,selected,entry,exit,mark,points,comparison_quantity:qty,estimated_rupees:points!=null&&qty!=null?points*qty:null,
      state:!leg?'LEG DATA UNAVAILABLE':points==null?'PRICE DATA INCOMPLETE':isClosed?'OBSERVED CLOSED':shadow.status==='ACTIVE'?'OBSERVED ACTIVE':'EXIT DATA PENDING'}
  })
}
