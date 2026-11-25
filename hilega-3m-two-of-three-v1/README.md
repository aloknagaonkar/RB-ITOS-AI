# Hilega: 3-minute candles, any 2 of 3, session-end closure

Status: source candidate prepared; not installed and not runtime-validated.
No strategy execution, pytest, builds, historical comparisons or broker requests
were run while preparing this package. The VM validation below must pass before
installation is considered. There is deliberately no apply command in this package.

## Approved behaviour

- Completed 3-minute candles, anchored at 09:15 IST. First decision 09:18;
  next confirmation 09:21. Indicator periods remain RSI9, EMA3(RSI9),
  WMA21(RSI9), and price EMA10, all calculated on 3-minute candles.
- At initial qualification, qualified-opposite replacement and the follow-up
  fresh-check route: any 2 of positive directional EMA/WMA gap, directional
  WMA change >=0.75, expanding directional gap. Missing/nonfinite evidence blocks.
- Full initial alignment remains mandatory. Bullish signal gap >=2 and full
  WMA movement >=2 remain separate. Consequently the positive-gap vote is
  already satisfied at an aligned initial signal; either strength or expansion
  can fail there, but not both.
- Existing directional colour/RSI checks remain. Follow-up is still
  colour AND RSI direction AND (price confirmation OR fresh 2-of-3 route).
  A valid price route can bypass the vote threshold; missing indicators cannot.
- Initial EMA10 side/slope checks, bullish extra minima, touch retention,
  manual reset and strict WMA40 bearish exit permission remain.
- Entries, follow-ups, normal exits and bullish reversal monitoring use 3m.
  Signals and entries after 14:55 are allowed. The last entry boundary is 15:27;
  15:30 cannot open or reverse a position.
- At regular-session end (15:30), close the strategy position and clear pending
  state/monitor. The exact 15:29 close is the underlying and option-shadow
  closing mark. Never require a nonexistent 15:30 minute OPEN. Missing evidence
  stays waiting/pending; do not invent a close or mark an actual broker account flat.
- Single position and exit-before-entry ordering remain in force.

## Actual execution limitation

The existing application runs observation/preparation flows. This package does
not enable broker execution, alter risk controls, or migrate production workspace
policy/version enrollment. Historical/shadow closing marks are not broker fills.
An order first sent at 15:30 cannot be assumed executable before the market closes.
Before actual trading release, validate a pre-close square-off submission deadline
against the broker/product, retry/reconcile exits, and verify the broker position
is flat. That execution deadline must not be invented from a candle mark.
Special trading sessions require an authoritative session schedule before release;
this candidate implements the regular 09:15–15:30 session only.

## Files and compatibility

The new implementation is static source in
`backend/market_lab/hilega_three_minute_v1/`. Three entry-point wrappers select it:
`hilega_combined_policy_v1.py`, `hilega_alignment_dual_exit_live_v1.py`, and
`hilega_combined_replay_v1.py`. Legacy shared signal engines remain unchanged.
The namespace contains its own adapted bullish/bearish/coordinator/opening engines.
No runtime string conversion, exec, or research-engine imports are used.

Shared option lifecycle start APIs gain an interval argument with default 5;
the 3m live coordinator supplies 3. Their session-end shadow valuation uses the
last completed minute close. Existing non-session-end exits retain exact OPEN.
UI projection displays recorded vote count and correct timeframe/session-end,
does not erase post-14:55 replay decisions, and does not mix reconstructed 5m
rows into a session with recorded 3m evidence. Legacy `completed_5m_indicators`
and related response keys remain compatibility aliases, explicitly accompanied
by 3m timeframe/version metadata; their values come from the 3m engine.

Policy ID stays `BULLISH_GAP2_FULL_WMA2` for established routing compatibility.
Version becomes `bullish-gap2-full-wma2-3.0.0-3m-two-of-three-session-close`.
Replay output uses its own directory and source fingerprint including every
new namespace module. Existing validated replay proofs cannot validate this version.

## 1. Compare installed VM source

Extract the ZIP inside `~/RB-ITOS-AI`, then:

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -B hilega-3m-two-of-three-v1/stage.py --check
```

If `SOURCE_MISMATCH` is returned, stop and share that JSON. It names files that
differ from the inspected snapshot. There is no force option; preserve newer VM
fixes and update the candidate against them before proceeding. No secrets are
included in the check output.

## 2. Stage away from the running application

Use a fresh directory; existing directories are deliberately not overwritten.

```bash
.venv/bin/python -B hilega-3m-two-of-three-v1/stage.py \
  --stage /tmp/hilega-3m-two-of-three-stage-v1
```

This copies backend/frontend source to a separate directory and overlays the
candidate. Existing frontend dependencies are referenced for the offline build.
Do not start an API/worker from the stage against the live application's data.
No running files, services, databases, credentials or execution flags are changed.

## 3. Run validation on Ubuntu

Choose saved complete sessions with at least 20 prior complete warmup sessions.
The example dates are known research sessions, not a claim that all files exist
on your VM. Missing inputs block validation and must be supplied, not synthesized.

```bash
.venv/bin/python -B hilega-3m-two-of-three-v1/validate.py \
  --stage /tmp/hilega-3m-two-of-three-stage-v1 \
  --days 2026-10-22 2026-10-23 2026-10-26 \
  --output /tmp/hilega-3m-two-of-three-validation-v1
```

It runs candidate tests, existing CE option lifecycle/bridge regressions, the
staged frontend build, and three comparisons on identical saved inputs:

1. Installed 5m / 3-of-3 / 14:55 cutoff.
2. Candidate 3m / 3-of-3 / 15:30 end.
3. Candidate 3m / 2-of-3 / 15:30 end.

Variants 2 and 3 isolate the vote change. Variant 1 versus 2 changes both
timeframe and session duration; do not attribute that difference solely to timeframe.
For both candidate variants, the real live coordinator is fed saved minutes with
option callbacks stubbed and manual controls disabled in that offline process.
Its entry/exit timestamps, directions and prices must match replay, callbacks
must be exit-first, and session-end ownership must be flat/locked.

Per-session JSON includes trades, points, worst trade, closed-trade drawdown,
give-back, entries after 14:55, failed vote conditions and confirmation routes.
Results exclude fees, slippage and actual option/broker execution.

Share `validation.json`, failed logs (if any), and
`comparison/comparison.json` before the installation step is prepared.
Passing offline validation does not authorize or certify live broker execution.
