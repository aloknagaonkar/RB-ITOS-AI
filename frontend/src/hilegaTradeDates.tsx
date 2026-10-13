import {type ReactNode} from 'react'
export function istDay(value:string|number|Date=Date.now()):string{
 const d=new Date(value);if(Number.isNaN(d.getTime()))return ''
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(d)
 const pick=(type:string)=>parts.find(p=>p.type===type)?.value??''
 return `${pick('year')}-${pick('month')}-${pick('day')}`
}
export function sessionDay(value:string|null|undefined):string{return value?istDay(value):''}
export function dateOptions(days:string[]):string[]{return [...new Set(days.filter(Boolean))].sort().reverse()}
export function recentAuditDays(days:string[],today=istDay()):string[]{
 const previous=dateOptions(days).find(day=>day<today)
 return previous?[today,previous]:[today]
}
export function selectedTradeDay(selected:string,days:string[],today=istDay()):string{return selected|| (days.includes(today)?today:days[0]??today)}
export function TradeDateFilter({value,dates,onChange,children}:{value:string;dates:string[];onChange:(value:string)=>void;children?:ReactNode}){
 return <div className="hime-controls"><label>Session date <select value={value} onChange={e=>onChange(e.target.value)}>{dateOptions([istDay(),...dates,value]).map(d=><option key={d} value={d}>{d}</option>)}</select></label>{children}</div>
}
