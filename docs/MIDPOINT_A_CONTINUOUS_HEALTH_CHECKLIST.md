# Midpoint A + Continuous Health Checklist

## Frozen architecture

- `A_ENTRY` is observation-only and runs in a parallel lane.
- A never sets `active_reference_type`; therefore it cannot suppress B, E,
  B_REARM, PM_B, or PM_E.
- `CURRENT_EXIT_POLICY` is the unchanged control.
- `HEALTH_IMMEDIATE_CONFIRMATION` arms on an existing soft control exit and
  exits at the first completed unhealthy one-minute close.
- `HEALTH_TWO_CLOSE_CONFIRMATION` arms on the same signal and exits at the
  second consecutive completed unhealthy one-minute close.
- A healthy close resets the two-close streak. An unavailable health close
  neither confirms nor resets it.
- Structural midpoint invalidation is the hard fallback for both health paths.
- All candidate fills use the observed completed NIFTY close. No theoretical
  floor and no future candle is used.

## Soft signals consumed

- `NORMAL_B_PROVED_EXIT_CANDIDATE`
- `DEGRADED_EXIT_CANDIDATE_TRIGGERED`

The engine does not invent a new target or threshold. T+5 observations remain
separate research candidates and are not silently promoted into the control.

## Safety invariants

- `observation_only = true`
- `execution_enabled = false`
- `paper_order_enabled = false`
- `quantity = None`
- `order_sent = false`

## Validation sequence

- [ ] Install and run the targeted test suite.
- [ ] Restart API and live-shadow only after installation passes.
- [ ] Confirm workspace gates show A and continuous health enabled.
- [ ] Run the fixed 490-session comparison.
- [ ] Inspect overall and per-entry-kind results for A, B, E, B_REARM,
      E_REARM, PM_B, and PM_E.
- [ ] Confirm the current-control result is unchanged from its own event path.
- [ ] Compare mean points, win rate, MFE giveback, and unresolved counts.
- [ ] Review the 2026-10-01 live audit section.
- [ ] Do not promote either health policy until frozen OOS and forward behavior
      are acceptable by family and direction.
