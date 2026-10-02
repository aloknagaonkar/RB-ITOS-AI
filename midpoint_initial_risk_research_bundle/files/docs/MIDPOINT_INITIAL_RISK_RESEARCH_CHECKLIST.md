# Midpoint Initial-Risk Research Checklist

Scope: observation-only research for B, E, and C entries that have not yet
proved +20 points. Existing `NORMAL_B_PROVED` and `DEGRADED_EXIT_CANDIDATE`
management is frozen and must not be changed by this sprint.

## Frozen research contract

- [x] Use all 480 chronological sessions.
- [x] Development block: first 336 sessions (70%).
- [x] Locked OOS block: final 144 sessions (30%).
- [x] Evaluate every candidate on every entry while the entry is unproved.
- [x] Do not select trades using knowledge that they remain unproved later.
- [x] Require exact completed one-minute candles; never substitute a nearby minute.
- [x] Report same-candle proof/stop ordering as `SIMULTANEOUS_PROOF_STOP_AMBIGUITY`.
- [x] Preserve proved-runner routes byte-for-byte.
- [x] Underlying points only in this phase; options, spreads, charges, and quantity excluded.

## Baseline cohorts

- [x] `UNPROVED`: no +20 proof before the original exit.
- [x] `PROVED_CLASSIFIER_MISSING`: +20 proved, but exact proof+10 classification unavailable.
- [x] `PROVED_CANDIDATE_NOT_TRIGGERED`: proved/classified, but the selected management candidate never exited before structural terminal.
- [x] `SESSION_UNRESOLVED`: original replay has no selected exit.
- [x] `PROVED_CANDIDATE_MANAGED`: control cohort used to measure damage to existing winners.

## Standalone candidates

- [x] `BOUNDARY_RECAPTURE`: first completed close back inside the broken boundary.
- [x] `FIXED_CLOSE_LOSS_15`: first completed close at or below -15 directional points.
- [x] `BOUNDARY_VWAP_ZERO_FAILURE`: boundary recapture plus futures-minus-VWAP sign reversal.
- [x] `INACTIVITY_12M_NO_PLUS10`: at exact entry+12 close, exit if running intrabar MFE is below +10.
- [x] Candidates are tested separately; no combined rule is optimized in this phase.

## Implementation

- [x] Add research runner: `scripts/research_midpoint_initial_risk_exits.py`.
- [x] Add development-only cohort and policy reports.
- [x] Add immutable policy-lock workflow.
- [x] Add one-time OOS validation receipt.
- [x] Add folder-preserving copy bundle.
- [ ] Validate the 2026-09-30 live session before running development research.
- [ ] User runs development phase.
- [ ] Review IS elimination matrix and ambiguity sensitivity.
- [ ] Select one policy and one ambiguity convention.
- [ ] Create policy lock.
- [ ] Run OOS validation once.
- [ ] Decide whether evidence supports observation-only live integration.
- [ ] If accepted, separately add exact next-minute option valuation research.

## Commands

Development only (does not expose OOS outcomes):

```bash
PYTHONPATH=backend:. python scripts/research_midpoint_initial_risk_exits.py \
  --phase develop
```

After reviewing the development report, lock exactly one policy. Example:

```bash
PYTHONPATH=backend:. python scripts/research_midpoint_initial_risk_exits.py \
  --phase lock \
  --policy BOUNDARY_VWAP_ZERO_FAILURE \
  --ambiguity proof-first
```

Run the locked OOS once:

```bash
PYTHONPATH=backend:. python scripts/research_midpoint_initial_risk_exits.py \
  --phase validate-oos
```

## Safety acceptance

- [x] No API, worker, UI, `.env`, live audit, order, paper order, or quantity mutation.
- [x] `observation_only=true` in output metadata.
- [x] `execution_enabled=false` in output metadata.
- [x] `paper_order_enabled=false` in output metadata.
- [x] `quantity=null` and `order_sent=false` in output metadata.
