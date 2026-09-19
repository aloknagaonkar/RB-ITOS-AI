# Historical OI Dual-Basket Calculations V1.3

Fixes missing fixed-basket calculations for newly built dates.

The raw sidecar now uses a two-phase build:
1. build normal current moving ATM ±5;
2. inspect the full day's moving ATM drift from the frozen 09:20 ATM;
3. automatically expand raw sidecar wings only as much as required to contain
   both current moving ±5 and frozen 09:20 ±5 at every timestamp.

The analytical moving basket remains exactly ±5.

Built-date audit now calculates:
- moving same-physical-strike 5m/10m/15m CE/PE delta OI
- CE/PE percentage change for each horizon
- imbalance for each horizon
- prior/current/change PCR for each horizon
- fixed 09:20 ATM ±5 baseline/current CE/PE OI
- fixed session CE/PE delta and percentage change
- fixed session imbalance
- fixed baseline/current/change PCR

Existing dates built under raw wings=5 must be rebuilt once after applying V1.3.
