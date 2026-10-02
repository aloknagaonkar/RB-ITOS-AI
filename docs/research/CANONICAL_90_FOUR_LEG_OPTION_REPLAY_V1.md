# Canonical 90 Four-Leg Option Replay V1

Purpose:
Compare exact ATM / OTM1 / OTM2 / OTM3 option-buying economics for the same
futures-aligned canonical signals using one unchanged execution policy.

Population:
- 370 TRADE_ELIGIBLE signals.
- Four exact option legs per signal.
- Coverage V1 established 1,448 READY legs and 32 SESSION_END_CENSORED legs.
- 362 signals have all four legs READY.

Leg mapping:

BULLISH:
- ATM  offset 0 CE
- OTM1 offset +1 CE
- OTM2 offset +2 CE
- OTM3 offset +3 CE

BEARISH:
- ATM  offset 0 PE
- OTM1 offset -1 PE
- OTM2 offset -2 PE
- OTM3 offset -3 PE

Entry:
- exact next-minute OPEN after C2.

Frozen exit policy:
`SL5_BE5_TRAIL3_AFTER10_TIME15`

Execution engine:
This module imports `replay_policy()` from
`structure_price_lag_option_exit_validation_v1` so stop-gap, stop-touch,
next-bar BE/trailing activation, exact +15 minute time exit, and 0.5
percentage-point research cost remain identical to the established engine.

Comparison discipline:
The headline leg comparison includes a separate common-denominator view using
only signals where all four legs are available. This avoids comparing strike
legs on different signal populations.

Outputs:
- `data/historical-evidence/canonical-90-four-leg-option-replay-v1.json`
- `data/historical-evidence/canonical-90-four-leg-option-replay-v1.csv`

Governance:
The 90-session population is already exposed. Results are descriptive research,
not fresh validation, and do not authorize paper/live execution.
