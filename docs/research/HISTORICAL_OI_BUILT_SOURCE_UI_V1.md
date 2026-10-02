# Historical OI Built Source UI V1

Adds a separate `Newly built dates` source alongside the frozen canonical 90-session source.

Built-date conversion:
- reads isolated `historical-oi-build/<date>/positioning.json`
- emits 74 checkpoints from 09:20 through 15:25
- sums CE/PE OI over the exact current ±5 moving basket
- computes same-physical-strike 5-minute CE/PE delta and percentage change
- computes previous/current/change PCR
- exposes exact ATM 5-minute positioning states and premium percentage changes
- keeps the canonical 90-session file untouched

Forward +5/+10/+15 spot movement remains retrospective evaluation context only.
