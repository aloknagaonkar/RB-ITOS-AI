# Canonical 90 Nine-Leg Option Replay V1

Purpose:
Compare four ITM strikes, ATM, and four OTM strikes for the exact same
futures-aligned canonical signals.

Population:
- 370 TRADE_ELIGIBLE signals.
- 3,330 theoretical option legs.
- Coverage V1 established:
  - 3,258 READY legs;
  - 72 SESSION_END_CENSORED legs;
  - 362 signals with all nine legs READY.

Strike mapping:

BULLISH / CE:
- ITM4 ATM-4
- ITM3 ATM-3
- ITM2 ATM-2
- ITM1 ATM-1
- ATM
- OTM1 ATM+1
- OTM2 ATM+2
- OTM3 ATM+3
- OTM4 ATM+4

BEARISH / PE:
- ITM4 ATM+4
- ITM3 ATM+3
- ITM2 ATM+2
- ITM1 ATM+1
- ATM
- OTM1 ATM-1
- OTM2 ATM-2
- OTM3 ATM-3
- OTM4 ATM-4

Entry:
- exact next-minute OPEN after C2.

Frozen exit policy:
`SL5_BE5_TRAIL3_AFTER10_TIME15`

Execution engine:
Imports the existing `replay_policy()` from
`structure_price_lag_option_exit_validation_v1`.

Therefore all legs use identical:
- -5% initial stop;
- open-gap-before-low-touch stop resolution;
- +5% BE arming;
- +10% trailing arming;
- 3% trailing distance;
- next-bar-only BE/trailing activation;
- exact entry+15 minute close time exit;
- 0.5 percentage-point round-trip research cost.

Comparison discipline:
The key strike comparison uses only events where all nine legs are available.
For the current coverage gate this should be 362 signals / 3,258 legs.

Outputs:
- `data/historical-evidence/canonical-90-nine-leg-option-replay-v1.json`
- `data/historical-evidence/canonical-90-nine-leg-option-replay-v1.csv`

Governance:
The canonical 90 population is already exposed. This is descriptive research,
not fresh validation, and does not authorize paper or live execution.
