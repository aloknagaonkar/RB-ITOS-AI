# Historical OI Enrichment V1

This module fills missing Historical OI Research calculation fields from the
isolated downloaded/built positioning dataset without modifying the frozen
canonical 90-session file.

Inputs:
- canonical `oi-pattern-library-90d-historical-only-v1.csv`
- isolated built `historical-oi-build/<date>/positioning.json`

Exact rules:
- exact 09:20 anchor only;
- frozen fixed ATM ±5 = 11 physical strikes;
- exact timestamp only;
- no nearest timestamp;
- no nearest strike;
- no interpolation;
- no synthetic OI;
- moving 5/10/15 minute comparisons use the SAME physical current strike basket.

Calculated fields:
- fixed CE/PE baseline OI;
- fixed CE/PE current OI;
- session CE/PE ΔOI;
- session CE/PE percentages;
- session imbalance;
- baseline/current/change PCR;
- moving same-strike 5/10/15 CE/PE OI, deltas, imbalance and PCR.

If exact data is missing, status remains SOURCE_MISSING.

This is historical research enrichment. It does not create production-equivalent
historical snapshots and does not make a date strict-replay ready.
