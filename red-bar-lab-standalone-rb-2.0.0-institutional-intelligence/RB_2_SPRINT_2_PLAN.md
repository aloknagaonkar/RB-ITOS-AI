# RB-2.0 Sprint 2 — Institutional Strength & Flow Dynamics

## Objective

Turn persisted ONLINE option-chain snapshots into a read-only institutional market narrative that explains whether buying or selling pressure is strengthening, weakening, rotating, expanding or exhausting.

Sprint 2 is advisory intelligence only. It MUST NOT modify Primary decisions, Committee eligibility, Opportunity selection, Portfolio, Queue, Exit or execution state.

## Inputs

- Persisted ONLINE option-chain snapshots only.
- Strike-level CE/PE open interest.
- Strike-level CE/PE option premium/LTP.
- Sprint-1 institutional flow classification and confidence.
- Snapshot timestamps for point-in-time comparison.

No reconstructed future data may be used.

## Modules

### 1. OI Velocity

For every CE/PE strike, compare current OI with snapshots at or before approximately 1, 5 and 15 minutes earlier.

Outputs:
- OI velocity 1m %
- OI velocity 5m %
- OI velocity 15m %
- OI acceleration
- STABLE / RISING / FALLING / ACCELERATING_UP / ACCELERATING_DOWN / REVERSING / MIXED

Purpose: distinguish static high OI from fresh institutional participation.

### 2. Premium Flow

Measure option-premium movement over the same 1m/5m/15m windows.

Outputs:
- Premium velocity
- Premium strength
- COMPRESSION
- EXPANSION
- EXPANSION_ACCELERATING
- DECAY
- EXHAUSTION
- REVERSAL_EXPANSION
- MIXED

Purpose: determine whether option price confirms or rejects OI activity.

### 3. Strike Rotation

Calculate OI-weighted call and put concentration centres in consecutive snapshots and measure migration.

Outputs:
- previous/current call centre
- previous/current put centre
- call shift
- put shift
- STABLE / UPWARD_ROTATION / DOWNWARD_ROTATION / DIVERGENT_ROTATION
- rotation confidence

Purpose: detect where institutional positioning is moving instead of looking only at one fixed call/put wall.

### 4. Buying / Selling Strength

Aggregate Sprint-1 directional flow and Sprint-2 OI velocity alignment.

Outputs:
- Buying Strength %
- Selling Strength %
- Neutral Strength %
- Net Strength
- Breadth
- LOW / MEDIUM / HIGH / HIGH_CONFLICT conviction

Purpose: answer the practical question: which side currently has stronger institutional evidence?

### 5. Institutional Confidence Index (ICI)

Combine five advisory components:
- Directional Edge — 35%
- OI Velocity — 20%
- Premium Flow — 20%
- Strike Rotation — 10%
- Breadth — 15%

The score is reduced when snapshot/data coverage is incomplete.

Outputs:
- ICI score 0-100
- BULLISH / BEARISH / NEUTRAL direction
- INSUFFICIENT / WEAK / MODERATE / STRONG / VERY_STRONG quality
- component scores
- data coverage
- execution impact = NONE

## Runtime Flow

ONLINE option-chain snapshots
→ Sprint-1 OI behaviour / buying-writing classification
→ OI Velocity + Premium Flow + Strike Rotation
→ Buying/Selling Strength
→ Institutional Confidence Index
→ Institutional Intelligence UI

## UI

Institutional Intelligence displays:
- Buying Strength
- Selling Strength
- Net Strength
- Market Conviction
- ICI
- ICI direction and quality
- snapshot coverage
- Strike Rotation
- confidence components
- strike-level OI Velocity
- strike-level Premium Flow

The page must continuously state that execution impact is NONE.

## Validation / Definition of Done

Sprint 2 is complete when:

1. 1m/5m/15m OI calculations are reproducible from persisted snapshots.
2. Premium-flow states are reproducible from persisted premium history.
3. Strike rotation is calculated from consecutive snapshots.
4. Empty or insufficient history fails safely to WAITING/neutral output.
5. ICI remains advisory and cannot receive execution authority.
6. Existing Primary, Committee, Opportunity, Portfolio, Queue and Exit behavior remains unchanged.
7. Unit tests cover the above invariants.

## Deliberately Deferred

Do NOT add these to Sprint 2:
- Previous-session carry-forward bias.
- Gap/opening narrative.
- Automatic threshold tuning.
- Candidate promotion based on ICI.
- Trade execution based on institutional confidence.

Those belong to later RB-2.0 work and must be introduced additively after Sprint 2 is validated.
