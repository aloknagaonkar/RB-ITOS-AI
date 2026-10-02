# Canonical 90 Exact ATM Option Replay V1

This module applies the already-existing frozen option exit engine to the
Canonical 90 decision-audit population.

Population:
- 370 TRADE_ELIGIBLE signals from the canonical decision audit.
- 362 READY exact ATM option paths from Coverage Gate V1.1.
- 8 SESSION_END_CENSORED events remain excluded from 15-minute replay.

Entry:
- BULLISH -> exact C2 moving ATM CE.
- BEARISH -> exact C2 moving ATM PE.
- exact next-minute OPEN after C2.
- no nearest-strike fallback.
- no nearest-time fallback.

Frozen exit policy:
`SL5_BE5_TRAIL3_AFTER10_TIME15`

Parameters:
- initial stop: -5%
- breakeven trigger: +5%
- trailing activation: +10%
- trailing distance: 3%
- maximum hold: 15 minutes
- round-trip research cost: 0.5 percentage points

Execution semantics are not reimplemented. The module imports and calls
`structure_price_lag_option_exit_validation_v1.replay_policy`, preserving:
- active stop checked at the start of each bar;
- gap through stop exits at bar OPEN;
- low touching stop exits at active stop price;
- BE/trailing updates become active next bar only;
- time exit uses exact entry+15 minute CLOSE.

Outputs:
- JSON:
  `data/historical-evidence/canonical-90-exact-atm-option-replay-v1.json`
- CSV:
  `data/historical-evidence/canonical-90-exact-atm-option-replay-v1.csv`

Governance:
This 90-session population is already exposed by prior research. Results are
descriptive research only and must not be described as fresh validation.
No paper or live orders are emitted.
