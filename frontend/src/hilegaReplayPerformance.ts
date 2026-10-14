// Preserve selected-strategy audits; combine only same-session metric summaries.
const IDs=['LIVE_RECORDED_V1','HILEGA_V1_REPLAY','HILEGA_WMA_GAP_V2_REPLAY','HILEGA_V2_ALIGNMENT_DUAL_EXIT_REPLAY_V1']
export function replayPerformance(day:string,selected:any,baseline:any,alignment:any,baselineError:string,alignmentError:string){
 const rows=new Map<string,any>()
 for(const source of [baseline,alignment,selected]){
  if(source?.session_date!==day)continue
  for(const row of source.performance_summary??[])rows.set(row.strategy_id,row)
 }
 return IDs.map(id=>rows.get(id)??{strategy_id:id,available:false,unavailable_reason:id===IDs[3]?alignmentError||'Tested V2 metrics unavailable for this date':baselineError||'Baseline metrics unavailable for this date'})
}
