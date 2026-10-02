# V55 — Boundary classifier and replay parity

V55 deliberately separates **selection logic** from the live coordinator.

It adds one pure classifier:

- fresh Candidate A at boundary -> OTHER_FRESH_A
- Candidate A false + mature directional VWAP -> E
- Candidate A false + not mature -> B watch

No live-shadow behavior is changed in this phase.

Acceptance:
- ownership counts must exactly match frozen V53 in all four blocks
- 2026-09-28 09:26 bearish must replay as E
- 2026-09-28 09:58 bullish must replay as B
- no live enablement
- no order/execution changes

After V55 passes, V56 may wire this exact classifier into
`MidpointLiveShadowCoordinatorV1` behind explicit Family-E enablement.
