# Midpoint V2 Research Plan V1

## Frozen V1 baseline
- Entry: `MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2`
- Exit: `SL5_BE5_TRAIL3_AFTER10_TIME15`
- Exact moving ATM, exact next-minute OPEN
- V1 is immutable.

## V2 entry arms
1. `IMMEDIATE_CONTINUATION` — V1 path unchanged.
2. `BASE_THEN_GO` — only starts from `WAIT_BASE`; hold boundary, build controlled base, later same-direction expansion.
3. `FAILED_BREAK_RECLAIM` — only starts from `RECLAIM_WATCH`; boundary reclaim alone is insufficient; require midpoint reclaim and opposite-direction acceptance before reversal confirmation.

## V2 exit-duration policies
- `E15_V1_BASELINE`
- `HYBRID_TIME15_UNLESS_TRAIL_ACTIVE`
- `E20`
- `E30`
- `TRAIL_ONLY_AFTER_ACTIVATION_WITH_SAFETY_CAP`

Preferred hypothesis: at minute 15, exit weak/stagnant trades, but if +10% trailing had already activated, allow the winner to continue until its trailing stop (subject to a research safety cap).

## Metrics
Keep entry arms and exit policies separate: count, mean/median net, PF, win rate, avg winner/loser, payoff, best/worst, drawdown, streaks, MFE/MAE, MFE capture, duration, % beyond 15m, bullish/bearish summaries.

## Governance
Rule discovery only on `TRAIN + OOS_A + OOS_B + OOS_C + OOS_D`.
Never use `OOS_E/F/G/H` for V2 rule discovery. H is already consumed by V1.
Historical labels may diagnose outcomes but must not leak into candidate selection.

## Integration sequence
1. Unit tests.
2. Development-only schema probe.
3. Wire actual reference midpoint/boundary/post-T3 closes from real framework fields.
4. Structural counts before P&L.
5. Freeze V2 candidate definitions before economics.
6. Exact option economics.
7. Exit-duration comparison.
8. Select candidate on development data.
9. Validate on a genuinely fresh future OOS block.
