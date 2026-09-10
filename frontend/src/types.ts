export type Config = {
  name: string; provider: 'demo' | 'upstox'; underlying: string; expiry: string;
  wings: number; anchor_time: string; anchor_tolerance_seconds: number; interval_seconds: number;
  max_quote_age_seconds: number; max_collection_seconds: number;
}
export type Result = {
  mode: 'fixed'|'moving'|'full'; atm: number|null; strikes: number[]; contract_keys: string[];
  expected: number; received: number; put_oi: number; call_oi: number;
  put_prev_oi: number|null; call_prev_oi: number|null; put_change_oi: number|null; call_change_oi: number|null;
  put_change_pct: number|null; call_change_pct: number|null; pcr: number|null; issues: string[];
}
export type Evaluation = {
  engine_version: string; observed_at: string; anchor_status: string;
  anchor: null | { atm: number; captured_at: string; spot: number };
  results: Result[]; warnings: string[];
}
export type Point = { id: number; spot: number; evaluation: Evaluation; range_changed: boolean; recorded_at: string }
export type State = {
  config_id: number; config: Config; enabled: boolean; history: Point[]; observation_count: number;
  receipt_age_seconds: number|null; collection_overdue: boolean;
  worker: { state: string; alive: boolean; last_error?: string; heartbeat_age_seconds: number|null };
}
export type Detail = {
  id: number; config_id: number; evaluation: Evaluation; recorded_at: string;
  snapshot: {
    spot: number; received_at: string; started_at: string; spot_feed_at: string|null; oi_source_at: string|null;
    oi_unit: string; catalog: { key: string; strike: number; side: 'CE'|'PE' }[];
    quotes: { key: string; oi: number|null; prev_oi: number|null }[];
  };
}
