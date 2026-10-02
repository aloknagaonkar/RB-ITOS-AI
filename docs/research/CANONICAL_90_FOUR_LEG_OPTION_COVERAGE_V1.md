# Canonical 90 Four-Leg Option Coverage V1

Purpose:
Establish exact historical availability for the four option strikes requested
for every futures-aligned canonical signal before comparing economics.

Signal population:
- `TRADE_ELIGIBLE` events from Canonical 90 Decision Audit V1.
- Expected signal count from the current frozen audit: 370.
- Four legs per signal => expected 1,480 exact option legs.

Strike mapping:

BULLISH:
- ATM  = strike_offset 0 CE
- OTM1 = strike_offset +1 CE
- OTM2 = strike_offset +2 CE
- OTM3 = strike_offset +3 CE

BEARISH:
- ATM  = strike_offset 0 PE
- OTM1 = strike_offset -1 PE
- OTM2 = strike_offset -2 PE
- OTM3 = strike_offset -3 PE

Rules:
- exact C2 timestamp only;
- exact positioning strike-offset row only;
- exact instrument key only;
- exact next-minute OPEN after C2;
- require exact one-minute path through entry+15m;
- no nearest strike;
- no nearest timestamp;
- session-end missing minutes at 15:30+ are classified separately.

This is a coverage gate only. It does not calculate P&L.

Output:
`data/historical-evidence/canonical-90-four-leg-option-coverage-v1.json`

After coverage is accepted, the replay phase should apply the same frozen
`SL5_BE5_TRAIL3_AFTER10_TIME15` execution engine independently to every READY
leg and compare ATM / OTM1 / OTM2 / OTM3 descriptively on the exposed
canonical population.
