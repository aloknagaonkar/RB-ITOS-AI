import {useEffect,useState} from 'react'

export async function fetchLive(url:string,signal?:AbortSignal,timeoutMs=8000):Promise<Response>{
  const controller=new AbortController()
  const cancel=()=>controller.abort()
  signal?.addEventListener('abort',cancel,{once:true})
  if(signal?.aborted)cancel()
  const timer=window.setTimeout(cancel,timeoutMs)
  try{
    const response=await fetch(url,{signal:controller.signal,cache:'no-store'})
    // Consume the body inside the timeout, including stalled JSON transfers.
    const bytes=await response.arrayBuffer()
    return new Response(bytes,{status:response.status,statusText:response.statusText,headers:response.headers})
  }catch(e){
    if(controller.signal.aborted)throw new Error(`Display request timed out or cancelled (${timeoutMs/1000}s); strategy is unaffected`)
    throw e
  }finally{window.clearTimeout(timer);signal?.removeEventListener('abort',cancel)}
}

export function startLivePolling(run:()=>Promise<void>,intervalMs:number){
  let stopped=false,busy=false,pending=false,timer:number|undefined
  const poll=async()=>{
    if(stopped||document.hidden)return
    if(busy){pending=true;return}
    busy=true
    try{await run()}finally{
      busy=false
      if(!stopped){timer=window.setTimeout(()=>{pending=false;void poll()},pending?0:intervalMs)}
    }
  }
  const resume=()=>{if(!document.hidden){window.clearTimeout(timer);void poll()}}
  document.addEventListener('visibilitychange',resume);window.addEventListener('focus',resume)
  void poll()
  return ()=>{stopped=true;window.clearTimeout(timer);document.removeEventListener('visibilitychange',resume);window.removeEventListener('focus',resume)}
}

export function useActiveLiveMarks(){
  const [data,setData]=useState<any>(null),[error,setError]=useState('')
  const [received,setReceived]=useState(0),[clock,setClock]=useState(Date.now())
  useEffect(()=>{
    let active=true;const controller=new AbortController()
    const stop=startLivePolling(async()=>{
      try{
        const r=await fetchLive('/api/live-shadow/hilega-directional/active-live-marks',controller.signal,3000)
        if(!r.ok)throw new Error(`Live marks HTTP ${r.status}`)
        const value=await r.json()
        if(value.model!=='HILEGA_ACTIVE_LIVE_MARKS_V1')throw new Error('Unexpected live mark response')
        if(active){setData(value);setReceived(Date.now());setError('')}
      }catch(e){if(active)setError((e as Error).message)}
    },2000)
    const tick=window.setInterval(()=>setClock(Date.now()),1000)
    return()=>{active=false;controller.abort();stop();window.clearInterval(tick)}
  },[])
  const find=(trade:any,key:string)=>{
    const q=(data?.quotes??[]).find((x:any)=>x.instrument_key===key&&x.direction===trade.direction&&x.signal_boundary===(trade.signal_boundary??trade.signal_bar))
    const age=q?.quote_timestamp?clock-Date.parse(q.quote_timestamp):Infinity
    return !error&&received>0&&clock-received<=10000&&age>=0&&age<=10000&&q?.status==='LIVE'?q:null
  }
  return {data,error,received,find}
}
