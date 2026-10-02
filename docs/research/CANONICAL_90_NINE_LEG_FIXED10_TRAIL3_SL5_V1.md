# Canonical 90 Nine-Leg Fixed +10 Point Trail / -5% Stop V1

Purpose:
A clean A/B against the immediately preceding -10% stop experiment.

Only one parameter changes:
- previous experiment: initial stop = -10%;
- this experiment: initial stop = -5%.

Everything else remains fixed.

Entry:
- exact next-minute OPEN after C2;
- same TRADE_ELIGIBLE signals;
- same 9 strike legs;
- no nearest-strike fallback;
- no nearest-time fallback.

Exit policy:
`SL5_TRAIL3_AFTER_PLUS10PTS_TIME15`

Rules:
- initial stop = 5% below entry premium;
- no breakeven rule;
- trail arms when premium reaches entry + 10 absolute premium points;
- trail distance = 3 absolute premium points;
- new/ratcheted trail becomes active NEXT BAR ONLY;
- stop resolution = open gap first, then low touch;
- max hold = 15 minutes;
- exact entry+15 minute close for time exit;
- 0.5 percentage-point round-trip research cost.

This is an exposed-population descriptive experiment only, not validation and not
authorization for paper/live execution.

Outputs:
- data/historical-evidence/canonical-90-nine-leg-fixed10-trail3-sl5-v1.json
- data/historical-evidence/canonical-90-nine-leg-fixed10-trail3-sl5-v1.csv
