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
- [x] Validate the 2026-09-30 live session before running development research.
- [x] Freeze replacement hypothesis: remove C as a family and repeatedly rerun
  canonical B/E validation after every distinct midpoint-touch generation.
- [x] Add 480-session repeated B/E rearm research replay with first-generation
  parity comparison against current C.
- [x] Run repeated B/E rearm replay and review generation/churn distribution.
- [ ] Decide whether repeated B/E replaces C before initial-risk development.
- [ ] User runs development phase.
- [ ] Review IS elimination matrix and ambiguity sensitivity.
- [ ] Select one policy and one ambiguity convention.
- [ ] Create policy lock.
- [ ] Run OOS validation once.
- [ ] Decide whether evidence supports observation-only live integration.
- [ ] If accepted, separately add exact next-minute option valuation research.

## Repeated B/E rearm — 480-session result

- [x] First-generation parity passed: 480/480 sessions, zero failures.
- [x] Current C is therefore behaviorally equivalent to B/E generation 1 and
  can be relabelled without changing its entry chronology.
- [x] Origin generation 0: 355 entries, +258.35 completed points.
- [x] Generation 1: 89 entries, +519.80 points, mean +6.26.
- [x] Generation 2: 24 entries, 22 completed, +27.65 points, mean +1.26,
  median -7.15, 10 positive and 12 negative.
- [x] Generation 3: 6 entries, +88.90 points, mean +14.82, but sample is too
  small for a live conclusion.
- [x] Increment beyond current C: 30 entries, 28 completed, +116.55 points.
- [x] Full repeated model: 474 entries, 465 completed, +894.70 points versus
  current strategy 444 entries, 437 completed, +778.15 points.
- [x] Structural-baseline population increased to 200 entries and remained a
  major loss source; repeated rearm does not replace initial-risk research.
- [ ] Run chronological block and true forward-session stability for
  generations 2+ before enabling recursive rearm in live shadow.
- [ ] Separate decision A: relabel current C as B/E generation 1.
- [ ] Separate decision B: enable generations 2+ only if stability passes.
- [x] Implement repeated B/E live-shadow source behind
  `MIDPOINT_BE_REARM_SHADOW_ENABLED` with C mutually excluded.
- [ ] User installs, restarts, and verifies repeated B/E observation-only gate.
- [x] Implement `NORMAL_B` Tier-1 dual-failure classifier-close historical and
  live-audit diagnostic based on the 2026-09-30 loss.
- [ ] Run exit diagnostic and review historical damage/recovery before changing
  the live exit policy.

## Forward validation register

### 2026-09-30 through 11:19 IST

- [x] Safety passed: observation only, execution off, paper off, quantity null.
- [x] Chronology passed: 29 events, no duplicate event IDs.
- [x] B bearish 09:33 entry 22683.20; unproved structural exit 09:45 at
  -43.95 points.
- [x] C bearish 09:49 entry 22702.10; unproved structural exit 09:56 at
  -25.05 points.
- [x] E bullish 10:05 entry 22742.80; +20 proof at 10:20; exact proof+10
  `NORMAL_B` classification at 10:30.
- [x] E classifier evidence: close progress +4.70, MFE +29.00, progress check
  false, futures-VWAP change check false.
- [x] E remained Tier 1 because the existing Tier 2 condition is strictly
  MFE > +30; no floor or inactivity deadline was active.
- [x] E candidate and baseline both exited on midpoint invalidation at 10:34
  for -29.00 points.
- [x] The 10:34 terminal released `active_reference_type`; the candidate did
  not lock or halt the coordinator.
- [x] No later entry was eligible: the opening RED path had already produced
  B then C, the opening GREEN path had already produced E, and no post-E
  `C_MIDPOINT_TOUCH_ARMED` plus fresh boundary-close sequence was recorded.
- [x] D and PM_E remained disabled, DHANUSH remained research-only, and
  post-rescue/candidate re-entry remained disabled.
- [x] Total underlying result across the three independent shadow trades:
  -98.00 points.
- [x] Classification routing and candidate behavior matched the implemented
  rules; these are policy losses, not chronology or runtime defects.
- [ ] Add a separate, pre-registered `NORMAL_B` classifier-close diagnostic
  after the initial-risk development run. Do not tune a +29/+30 threshold from
  this single known forward session.

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
