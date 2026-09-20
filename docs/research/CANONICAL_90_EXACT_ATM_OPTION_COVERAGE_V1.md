# Canonical 90 Exact ATM Option Coverage Gate V1

Purpose: prove exact option replay coverage before applying any P&L or exit
policy.

Input candidates:
- only `TRADE_ELIGIBLE` events from Canonical 90 Decision Audit V1;
- expected population after current audit: 370.

Exact option rules:
- use the C2 timestamp;
- use the positioning row at that exact timestamp with `strike_offset == 0`;
- require `strike == moving_atm`;
- BULLISH -> exact ATM CE instrument;
- BEARISH -> exact ATM PE instrument;
- no nearest-strike fallback;
- no nearest-time fallback.

Entry:
- exact next-minute option candle OPEN after C2.

Coverage path:
- require the entry minute and every exact one-minute candle through
  entry+15 minutes inclusive.
- this is a coverage gate only; it does not calculate P&L or apply stops.

Expected status families:
- READY
- POSITIONING_SESSION_MISSING
- MISSING_EXACT_ATM_POSITIONING
- AMBIGUOUS_EXACT_ATM_POSITIONING
- INCONSISTENT_EXACT_ATM_POSITIONING
- MISSING_EXACT_ATM_INSTRUMENT
- OPTION_OHLC_SESSION_MISSING
- BLOCK_MISMATCH
- MISSING_ENTRY_MINUTE
- INVALID_ENTRY_OPEN
- OPTION_IDENTITY_MISMATCH
- INCOMPLETE_15M_PATH

Output:
`data/historical-evidence/canonical-90-exact-atm-option-coverage-v1.json`

After this gate is accepted, Phase 2B will apply the frozen
SL5_BE5_TRAIL3_AFTER10_TIME15 policy and 0.5 percentage-point research cost.
