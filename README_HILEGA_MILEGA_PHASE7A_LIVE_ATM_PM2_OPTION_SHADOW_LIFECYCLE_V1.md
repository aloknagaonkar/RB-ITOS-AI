# Hilega-Milega Phase 7A — Live ATM±2 CE Shadow Lifecycle V1

## Goal
Track all five exact CE contracts around signal-time ATM (`ATM-2`, `ATM-1`, `ATM`, `ATM+1`, `ATM+2`) through a complete live shadow lifecycle while preserving the canonical Hilega-Milega strategy and keeping all execution disabled.

This phase is not the deferred historical moneyness comparison. It creates the live evidence stream that Phase 7 Research can later analyze.

## Frozen shadow policy

- Side: CE only for bullish Hilega signals.
- Universe: exact `ATM±2`, 50-point strikes by current configuration.
- All five contracts are shadow-selected together; no single winner is chosen.
- Exact configured expiry only.
- Entry: exact 1-minute OPEN at the causal signal boundary (`5m label + 5 minutes`).
- Updates: completed option minutes only.
- Structural exit: exact 1-minute OPEN at the causal exit boundary (`exit 5m label + 5 minutes`).
- 14:55 cutoff: exact 14:55 option-minute OPEN.
- No nearest strike, nearest minute, interpolation, synthetic premium, quantity, paper order, or live order.

## New module

`backend/market_lab/hilega_milega_option_shadow_lifecycle_v1.py`

Audit stages:

- `OPTION_SHADOW_LIFECYCLE_START`
- `OPTION_SHADOW_LIFECYCLE_RESTORE`
- `OPTION_SHADOW_LIFECYCLE_UPDATE`
- `OPTION_SHADOW_LIFECYCLE_EXIT`

Each lifecycle payload contains all five legs with:

- strike and ATM relation
- exact instrument key and expiry
- entry timestamp/open
- latest completed option minute/close
- current premium points and return %
- MFE points/%
- MAE points/%
- exit open and realized points/% when closed

Safety fields remain explicit:

- `observation_only=true`
- `execution_enabled=false`
- `paper_order_enabled=false`
- `order_created=false`
- `quantity=null`

## Restart reconstruction

If the live worker restarts while the underlying Hilega strategy is `BULLISH_ACTIVE`, Phase 7A reconstructs the active option shadow lifecycle from the strategy's signal time/price/source, exact configured expiry, exact option contracts and exact option minute path. It emits `OPTION_SHADOW_LIFECYCLE_RESTORE` rather than a duplicate strategy signal.

## UI/API additive exposure

`GET /api/live-shadow/hilega-milega/status` now includes `latest_option_shadow`.

`GET /api/live-shadow/hilega-milega/option-shadow?limit=200` returns candidate, market-snapshot and lifecycle audit rows with hash-chain status.

## Tests

Relevant suite after Phase 7A:

```bash
python -m pytest \
  tests/test_hilega_milega_option_candidate_v1.py \
  tests/test_hilega_milega_option_snapshot_v1.py \
  tests/test_hilega_milega_option_economics_research_v1.py \
  tests/test_hilega_milega_option_shadow_lifecycle_v1.py \
  tests/test_hilega_milega_strategy_v1.py \
  tests/test_hilega_milega_historical_replay_v1.py \
  tests/test_hilega_milega_live_shadow_v1.py \
  tests/test_live_shadow_step_audit_v1.py -v
```

Expected: `39 passed`.

## Standing checklist after Phase 7A

### Passed by tests / prior live evidence
- [x] canonical Hilega strategy unchanged
- [x] Route A rule preserved
- [x] Route B rule preserved
- [x] immediate RSI↓WMA structural exit preserved
- [x] exact completed underlying 5m only
- [x] partial 5m live tail ignored
- [x] session-boundary previous strategy state reset
- [x] 14:55 cutoff semantics tested at exact 1m open
- [x] hash-chain audit preserved
- [x] option candidate set exact / no nearest strike
- [x] Phase 5 exact minute snapshot / no nearest minute
- [x] Phase 6 causal exact-option economics
- [x] Phase 7A all five ATM±2 CE shadow-selected together
- [x] Phase 7A exact causal option entry open
- [x] Phase 7A completed-minute MFE/MAE/current premium tracking
- [x] Phase 7A exact causal structural-exit option open
- [x] Phase 7A restart reconstruction path
- [x] quantity absent
- [x] paper order disabled
- [x] live execution disabled

### Still pending natural live validation
- [ ] fresh Phase 5 candidate set with corrected expiry
- [ ] fresh Phase 5 exact candidate market snapshot with corrected expiry
- [ ] Phase 7A live lifecycle START for all five exact CE contracts
- [ ] Phase 7A minute UPDATE records for all five legs
- [ ] Phase 7A live lifecycle EXIT mapped to a structural exit
- [ ] genuine Route B live entry parity
- [ ] natural 14:55 exact-open cutoff parity
- [ ] continue duplicate-worker / duplicate-candle monitoring

### Deferred, not forgotten
- [ ] Phase 7 Research: historical ATM-2 / ATM-1 / ATM / ATM+1 / ATM+2 comparison by Opening / Route A / Route B
- [ ] freeze final production contract-selection rule only after evidence
- [ ] automatic valid-expiry resolver from actual option-contract master
- [ ] persistent shadow trade ledger
- [ ] risk-engine quantity integration
- [ ] manual-approved paper trading
- [ ] controlled live trading
