export type PositioningHorizon = 300 | 900 | 1800
export type PositioningClassification = 'LONG_BUILDUP'|'SHORT_BUILDUP'|'LONG_UNWINDING'|'SHORT_COVERING'|'NEUTRAL'|'UNAVAILABLE'
export type StrikePositioningResult = {
  observation_id:number; configuration_version:number; received_at:string; instrument_key:string
  strike:number; side:'CE'|'PE'; horizon_seconds:PositioningHorizon
  current_ltp:number|null; baseline_ltp:number|null; price_change:number|null; price_change_pct:number|null
  current_oi:number|null; baseline_oi:number|null; observed_oi_change:number|null; observed_oi_change_pct:number|null
  baseline_received_at:string|null; actual_elapsed_seconds:number|null
  classification:PositioningClassification; status:'AVAILABLE'|'UNAVAILABLE'
}
export async function fetchStrikePositioning(configId:number, horizon:PositioningHorizon, centerStrike?:number, wings?:number):Promise<StrikePositioningResult[]> {
  const params = new URLSearchParams({config_id:String(configId), horizon_seconds:String(horizon)})
  if (centerStrike !== undefined && wings !== undefined) {
    params.set('center_strike', String(centerStrike)); params.set('wings', String(wings))
  }
  const response = await fetch(`/api/strike-positioning?${params}`)
  if (!response.ok) throw new Error('Strike Positioning unavailable')
  return response.json() as Promise<StrikePositioningResult[]>
}
