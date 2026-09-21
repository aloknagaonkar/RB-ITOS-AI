# LIVE_FIXED_SESSION_ANCHOR_RECOVERY_V1

Purpose: recover the configured fixed-session OI anchor when the live collector starts late, without moving the anchor or fabricating OI.

Frozen V1 semantics for a 09:20 anchor:
- prefer the existing first local live snapshot at/after 09:20 within +30 s;
- if that is absent/incomplete and this is the current IST session, use Upstox current-day V3 1-minute intraday candles;
- use the completed 09:19 candle for underlying spot and every option OI value;
- ATM uses the explicit 50-point NIFTY interval;
- basket is exactly ATM ± configured wings (wings=5 => 11 strikes / 22 contracts);
- every exact strike, side, timestamp and OI must exist;
- no nearest strike, no nearest timestamp, no interpolation, no synthetic OI, no partial fallback.

Provenance values:
- `ANCHOR_LIVE`
- `ANCHOR_RECOVERED_UPSTOX_INTRADAY_1M`
- `ANCHOR_MISSING`
- `NOT_APPLICABLE` for non-current/replay sessions

Recovered provenance records checkpoint time, source candle time, `COMPLETED_1M_BOUNDARY`, provider, spot, ATM, exact strikes/contracts, CE/PE totals, fixed PCR, and `fallback_used=false`.

Why 09:19 instead of the candle labelled 09:20: live cross-checks on 2026-09-21 showed same-label 1-minute OI can reflect state published during that minute. The completed previous minute avoids using information from after the 09:20 checkpoint.

Once an anchor is available, fixed-session metrics use the same exact 22 instrument keys at every live snapshot: CE delta, PE delta, session imbalance (`PE delta - CE delta`), baseline/current fixed-basket PCR, and PCR change. Missing any anchored contract at a checkpoint makes fixed-session metrics `INCOMPLETE` for that checkpoint.

The patch adds `FIXED_SESSION_ANCHOR` step-audit records and `fixed_session_anchor` / `fixed_session` fields to data-health JSONL. It does not modify moving 5/10/15-minute ALL3 calculations, C2, futures confirmation, option selection, entry, exit, paper orders, or broker execution.
