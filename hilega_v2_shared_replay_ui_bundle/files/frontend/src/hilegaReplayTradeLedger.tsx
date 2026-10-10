const tm=(x:any)=>x?new Date(x).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false,hour:'2-digit',minute:'2-digit'}):'—'
const num=(x:any)=>x==null?'—':Number(x).toFixed(2)
const signed=(x:any)=>x==null?'—':`${x>0?'+':''}${num(x)}`
export default function HilegaReplayTradeLedger({data,visibleUntil}:{data:any;visibleUntil?:string}){
 const trades=(data.trades??[]).filter((t:any)=>!visibleUntil||t.entry_time<=visibleUntil)
 const active=trades.filter((t:any)=>visibleUntil&&t.exit_time>visibleUntil)
 const closed=trades.filter((t:any)=>!visibleUntil||t.exit_time<=visibleUntil)
 const audit=[...(data.audit??[])].reverse().find((a:any)=>!visibleUntil||a.checkpoint<=visibleUntil)
 const table=(rows:any[],isActive:boolean)=><div className="shadow-table-scroll"><table className="shadow-table hilega-economics-table"><thead><tr><th>Direction</th><th>Setup</th><th>Signal IST</th><th>Entry IST</th><th>Entry Nifty</th>{isActive?<><th>Latest Nifty</th><th>Current points</th></>:<><th>Exit IST</th><th>Exit Nifty</th><th>Realized points</th><th>Exit reason</th><th>MFE</th><th>Giveback</th></>}</tr></thead><tbody>{rows.map((t:any)=><tr key={t.trade_id}><td>{t.direction}</td><td>{t.setup_source?.replaceAll('_',' ')}</td><td>{tm(t.signal_time)}</td><td>{tm(t.entry_time)}</td><td>{num(t.entry_price)}</td>{isActive?<><td>{num(audit?.nifty_close)}</td><td>{signed(audit?.active_trade?.nifty_points)}</td></>:<><td>{tm(t.exit_time)}</td><td>{num(t.exit_price)}</td><td className={t.points>=0?'positive':'negative'}>{signed(t.points)}</td><td>{t.exit_reason?.replaceAll('_',' ')}</td><td>{num(t.mfe_points)}</td><td>{num(t.giveback_points)}</td></>}</tr>)}</tbody></table></div>
 return <>
 <section className="panel shadow-panel"><div className="panel-heading"><div><h2>Active replay trade</h2><p>Nifty points at the selected replay checkpoint.</p></div><span className="pill teal">{active.length?`${active.length} ACTIVE`:'NO ACTIVE TRADE'}</span></div>{active.length?table(active,true):<div className="empty">No active replay trade at this checkpoint.</div>}</section>
 <section className="panel shadow-panel"><div className="panel-heading"><div><h2>Completed replay trades</h2><p>Entry and exit times are decision availability times in IST. Option fills were not reconstructed.</p></div><span className="pill">{closed.length} CLOSED</span></div>{closed.length?table(closed,false):<div className="empty">No completed trades at this checkpoint.</div>}</section>
 </>
}
