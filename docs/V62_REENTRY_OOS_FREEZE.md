# Midpoint V62 — Re-entry OOS Freeze

## Baseline

The currently validated management baseline is:

B/E entry
→ +20 proof
→ exact +10m classifier
→ DEGRADED
→ CAP20 rescue
→ EXIT
→ NO RE-ENTRY

## Why the 9 V61 cases are not OOS

R1 and R2 were chosen after reviewing those cases. Reusing them as "OOS" would
be circular. They remain development evidence only.

## Frozen research candidates

### R1 — Protect +10 after +20 proof

The existing post-CAP20 re-entry trigger is unchanged. If the second leg reaches
a favorable intrabar excursion of at least +20 points, exit on the first
completed 1-minute close whose directional move from the re-entry price is
<= +10 points.

### R2 — 20-point trail after +20 proof

The existing post-CAP20 re-entry trigger is unchanged. After running favorable
second-leg excursion first reaches +20, exit on the first completed 1-minute
close that is <= running second-leg MFE minus 20 points.

## Promotion gate

Do not promote either candidate until there are at least 20 new comparable
re-entry events; 30+ is preferred.

Use matched completed events only. Session-end marks and unresolved trades do
not count toward the matched terminal-comparable gate.

No threshold tuning is allowed after the forward OOS freeze begins.
