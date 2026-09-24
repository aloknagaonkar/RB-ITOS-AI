# Hilega Directional Master Checklist v1

## Completed baseline
- [x] Bullish Opening Path frozen
- [x] Bullish Route A frozen
- [x] Bullish Route B frozen
- [x] Bullish RSI-below-WMA structural exit frozen
- [x] Bullish 14:55 cutoff
- [x] Bullish historical replay
- [x] Bullish live-shadow observation
- [x] ATM±2 CE independent shadow lifecycle
- [x] Current-session bootstrap recovery
- [x] Active/Exited CE UI split
- [x] Latest completed candle first
- [x] Candle window + actual processing/recovery timestamp
- [x] Nifty delta + candle O→C display

## Bearish Phase B1/B2 — current
- [x] Bearish candidate rules documented as mirrored validation baseline
- [x] Separate `HilegaMilegaBearishEngineV1`
- [x] Reuse canonical RSI9 → EMA3/WMA21 indicator engine
- [x] Bearish Opening Path candidate logic
- [x] Bearish Route A candidate logic
- [x] Bearish Route B candidate logic
- [x] Bearish structural exit candidate logic
- [x] Bearish 14:55 cutoff semantics
- [x] Observation-only / execution-disabled safety flags
- [x] Hash-chain strategy audit coverage
- [x] Unit tests for Route A, Route B, ARMED persistence, exit, opening, cutoff, reset, audit
- [x] Historical replay integration for bearish engine
- [x] Manual-validation report generation (`bearish-manual-validation.txt`)
- [ ] Run replay on selected real bearish sessions
- [ ] Manually validate candle-by-candle bearish entries/exits
- [ ] Freeze or revise bearish rules based on evidence

## Directional orchestration — after bearish validation
- [ ] Add `HilegaDirectionalCoordinatorV1`
- [ ] ACTIVE state is exclusive
- [ ] Opposite ARMED state remains informational
- [ ] Opposite ARMED must not cancel the active trade
- [ ] Opposite ENTRY blocked while another direction is ACTIVE
- [ ] No same-candle reversal in v1
- [ ] After active EXIT, preserved opposite ARMED may continue on next completed candle
- [ ] Add conflict/arbitration audit fields
- [ ] Add directional unit and replay tests

## PE shadow lifecycle — after bearish rule validation
- [ ] ATM-2..ATM+2 PE candidate set
- [ ] Exact causal PE entry OPEN
- [ ] Latest PE premium
- [ ] PE current points / return
- [ ] PE MFE / MAE
- [ ] Exact causal PE exit OPEN
- [ ] PE realized points / return
- [ ] Pending-exact-exit behavior
- [ ] Restart/bootstrap recovery parity with CE
- [ ] Active PE UI
- [ ] Exited PE UI
- [ ] Live observation only; no quantity or order creation

## Live hardening still pending
- [ ] Full bootstrap recovery functional regression suite
- [ ] LIVE → FINALIZING → COMPLETE session lifecycle
- [ ] CE/PE evidence finalization before FULL status
- [ ] Live worker/candle staleness indicator
- [ ] End-of-day whole-session consistency validator

## Option selection research — intentionally after both directions
- [ ] Bullish CE ATM±2 outcome comparison
- [ ] Bearish PE ATM±2 outcome comparison
- [ ] Liquidity/spread gate research
- [ ] Delta-band research
- [ ] Resume parked ATM±2 vs ATM±5 OI/PCR structural research
- [ ] Fixed morning ATM vs moving ATM comparison
- [ ] IV / premium-efficiency research
- [ ] Route-specific selection research: Opening / Route A / Route B
- [ ] `CE_SELECTOR_V1` only after robust evidence
- [ ] `PE_SELECTOR_V1` only after robust evidence

## Directional invariant

```
ACTIVE = exclusive
ARMED = informational and may coexist with opposite ACTIVE
ENTRY = blocked while opposite direction owns ACTIVE trade
AFTER EXIT = preserved opposite ARMED may continue on next completed candle
NO same-candle reversal in v1
```


## Current decision after manual bearish review
- [x] 2026-09-15 complete bearish trade review
- [x] Route A/Route B behavior manually inspected on selected sessions
- [x] Bearish rules accepted to continue as current candidate baseline
- [ ] Whipsaw mitigation research — DEFERRED (do not modify rules yet)

## Directional Coordinator v1
- [x] Isolated coordinator module created
- [x] ACTIVE trade ownership is exclusive
- [x] Opposite ARMED state may coexist informationally
- [x] Opposite entry is blocked while current owner remains ACTIVE
- [x] Suppressed opposite entry is preserved as ARMED
- [x] Same-candle reversal is blocked
- [x] After exit, preserved opposite ARMED may continue on next completed candle
- [x] Coordinator unit regression suite
- [ ] Historical combined bullish+bearish replay through coordinator
- [ ] Manual combined-direction validation
- [ ] PE ATM±2 shadow lifecycle
- [ ] Live worker integration
- [ ] Combined directional UI
- [ ] CE/PE selection research
