# Canonical 90 Nine-Leg Fixed +10 Point Trail / -10% Stop V1

This is an isolated exit-policy experiment on the already exposed canonical
90-session signal population.

Entry logic is unchanged:
- same TRADE_ELIGIBLE signals;
- exact strike;
- exact next-minute OPEN after C2;
- no nearest-strike fallback;
- no nearest-time fallback.

Nine strikes:
- ITM4, ITM3, ITM2, ITM1, ATM, OTM1, OTM2, OTM3, OTM4.

Experimental exit policy:

`SL10_TRAIL3_AFTER_PLUS10PTS_TIME15`

Rules:
- initial stop = 10% below entry premium;
- no breakeven rule;
- trailing activates when option premium has traded at least 10 absolute premium
  points above entry;
- trailing distance = 3 absolute premium points below best observed premium;
- newly armed/ratcheted trail is active from the NEXT 1-minute bar only;
- before trail activation, only the initial -10% stop is active;
- stop resolution remains conservative: bar open gap first, then low touch;
- max hold = 15 minutes;
- time exit = exact entry+15 minute close;
- research transaction cost = 0.5 percentage points, same as prior studies.

Example:
- entry 100;
- initial stop 90;
- high reaches 110+ => trail arms;
- if best observed high is 111, next-bar stop is 108;
- if later best high becomes 116, following-bar stop becomes 113.

Important:
This changes only the exit policy for descriptive testing. It does not alter
signal generation, C1/C2 logic, futures alignment, strike selection, or authorize
paper/live trading.

Outputs:
- data/historical-evidence/canonical-90-nine-leg-fixed10-trail3-sl10-v1.json
- data/historical-evidence/canonical-90-nine-leg-fixed10-trail3-sl10-v1.csv
