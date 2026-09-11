export type PCRTrendClassification = 'RISING' | 'FALLING' | 'FLAT' | 'UNAVAILABLE'
export type PCRTrendStatus = 'AVAILABLE' | 'UNAVAILABLE'
export type PCRTrendResult = {
  record_id: number|null
  observation_id: number
  configuration_version: number
  record_kind: 'panel'|'strike'
  mode: 'fixed'|'moving'|'full'|'strike'
  strike: number|null
  requested_horizon_seconds: 60|300|900|1800
  current_pcr: number|null
  baseline_pcr: number|null
  absolute_pcr_change: number|null
  percentage_change: number|null
  actual_elapsed_seconds: number|null
  baseline_received_at: string|null
  classification: PCRTrendClassification
  status: PCRTrendStatus
}

export async function fetchLatestPanelTrends(configId: number): Promise<PCRTrendResult[]> {
  const response = await fetch(`/api/pcr-trends/latest?config_id=${configId}&panels_only=true&panels_only=true`)
  if (!response.ok) throw new Error('PCR trend data is unavailable')
  const values = await response.json() as PCRTrendResult[]
  return values.filter(value => value.record_kind === 'panel')
}
