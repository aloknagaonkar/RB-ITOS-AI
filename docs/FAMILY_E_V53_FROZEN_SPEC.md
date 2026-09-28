# Midpoint Strategy — Family E frozen specification V53

Status: RESEARCH FROZEN. Not live-enabled.

## Purpose

Family E covers structural boundary breaks where futures-VWAP directional
confirmation is already mature before the boundary break, so canonical
fresh Candidate A is false at T0.

## Boundary ownership

At each structural boundary event T0, the coordinator assigns exactly one owner:

1. Candidate A at T0 = TRUE
   - owner: OTHER_FRESH_A
   - neither B nor E owns the event.

2. Candidate A at T0 = FALSE and directional futures-VWAP is already mature:
   - BEARISH: futures close - session VWAP < -5
   - BULLISH: futures close - session VWAP > +5
   - owner: E
   - E entry timestamp: T0 boundary close.

3. Candidate A at T0 = FALSE and VWAP is not already mature:
   - owner: B
   - B watches up to 10 exact minutes for delayed full Candidate A.

One structural event may never be claimed by both B and E.

## Family B

Unchanged.

B remains the delayed-confirmation family:
- watch starts at original boundary break
- max delay 10 minutes
- exact 1m observations
- full delayed Candidate A requires:
  - canonical Candidate A true
  - directional midpoint structure still valid
  - price still beyond original boundary
- no same-event handoff from E back to B

## Family E

Entry qualification only is frozen in V53:
- valid structural boundary break
- canonical Candidate A false at boundary
- directional futures-VWAP already beyond +/-5
- immediate entry at boundary
- no mature-streak threshold
- no asymmetric bull/bear threshold
- no exit tuning

## Post-entry management

V53 does not implement new E management.

V54 is expected to reuse the existing B management unchanged:
- +20 proof
- exact +10m RUNNER_STRENGTHENING / DEGRADED classification
- PRIMARY_OFF
- DEGRADED first joint deterioration
- CAP20 rescue
- one post-rescue reentry
- no second rescue
- structural terminal

This preserves a clean experiment:
B vs E differ only in entry qualification; management remains identical.
