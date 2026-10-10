# Hilega tested V2 + Midpoint confirmation research

This is a separate offline experiment. It does not install or activate a strategy, change UI selections, arm Sandbox, or call broker/order APIs.

## Rules

- Rebuild Midpoint with installed coordinator and the observation-only family flags read from `.env` (environment overrides remain authoritative). Record the exact configuration in report.json.
- Confirmation is an accepted `SHADOW_ENTRY` from an enabled Midpoint family. Early breaks and blocked entries do not qualify. Family A confirmations count when A is enabled, even though A is a parallel lane; this choice is explicit and needs validation.
- A candle labeled 09:32 becomes available at 09:33. No future confirmation can approve an earlier entry.
- Bullish confirmation allows bullish Hilega setups only; bearish does the reverse.
- Check direction when a setup arrives AND before every pending entry evaluation. Unsupported setups are discarded, not queued until the trend changes. Hilega's own V2 entry gates still apply.
- Monitor every completed minute. A bullish close below its confirmed reference midpoint, or bearish close above it, makes trend neutral. Equality retains validity. A later accepted confirmation is required to restore direction. This is the new filter's explicit invalidation rule, not a claim that Midpoint has a pre-existing persistent trend service.
- Conflicting opposite confirmations at the same time, absent reference information, missing/stale minute evidence, or a new session mean neutral. The implementation requires complete matching Nifty/Midpoint data in the decision window; incomplete dates are not evaluated.
- Preserve V2 dual indicator exits, cutoff, and exit-before-replacement handling. A Midpoint trend change does NOT force an existing Hilega exit.
- Replay the full lifecycle with the filter; do not merely remove completed baseline trades after the fact.

## Run from RB-ITOS-AI

Extract this folder beside backend and scripts. No installer or restart is needed.

```bash
source .venv/bin/activate
PYTHONPATH=backend:. python hilega_midpoint_trend_validation/run.py --self-test
PYTHONPATH=backend:. python hilega_midpoint_trend_validation/run.py \
  --end-date 2026-10-09 \
  --output-root data/historical-evidence/hilega-midpoint-trend-validation-v1
```

The run evaluates July 10–October 9 and summarizes the last one and three calendar months. It needs local Nifty warmup and Midpoint historical minute files. Missing data is reported in coverage.csv, not treated as zero trades. Both variants' summaries use the same successfully evaluated dates. A partial result is not full-window validation.

Default Midpoint roots, later roots preferred:
- data/historical-evidence/hilega-pcr-oi-support-research-v1/midpoint-ui-replay-v1
- data/recovery/october-2026/midpoint
- data/recovery/october-2026/replay-input/midpoint

Other locations can be supplied with repeated `--midpoint-root PATH`; each root should contain YYYY-MM-DD/minutes.jsonl. Use repeated `--cache-root PATH` for different Nifty cache locations. This runner never downloads missing data. Choose a fresh output directory on every run; existing output is preserved.

## Date-wise and trade-wise outputs

- daily.csv: baseline and filtered trades, gains, losses, net, gain/loss ratios and net change for each date.
- trades.csv: both variants, signal time, entry/exit prices and times, direction, exit reason, Nifty points, entry gate evidence and Midpoint state at filtered entry.
- filter-checks.csv: every setup/entry check, whether allowed, and trend/rejection context.
- sessions/DATE/filtered.json: V2 audit plus continuous Midpoint timeline and checks.
- sessions/DATE/midpoint-events.json: rebuilt accepted/blocked Midpoint events.
- coverage.csv and report.json: input gaps, configuration and source hashes.

## Preliminary recovered-data results

Only October 6 and 7 inputs were available locally. Both Nifty and Midpoint OHLC match throughout the strategy window. Baseline reproduces the earlier tested V2 results.

| Date | V2 trades | V2 net | Filter trades | Filter gains | Filter losses | Filter net | Net change |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-10-06 | 7 | -50.70 | 3 | 9.45 | 31.50 | -22.05 | +28.65 |
| 2026-10-07 | 4 | +49.90 | 0 | 0 | 0 | 0 | -49.90 |
| Total | 11 | -0.80 | 3 | 9.45 | 31.50 | -22.05 | -21.25 |

`local_results` uses default Midpoint flags. `prior_config_sample` additionally uses the previously shared Family A, B/E rearm and continuous-health candidate flags. Trade totals are identical on these two dates; confirmation counts differ. Neither sample establishes the current VM configuration.

October 6 accepted bullish E confirmation: 09:32 candle, available 09:33 IST. Filtered bullish trades: 09:55→10:15 +9.45; 12:49→13:25 -13.10; 14:09→14:25 -18.40. Keeping the confirmation did not eliminate these losses.

October 7 default configuration had no accepted entry confirmation. With the previously shared flags, A bullish confirmation became available at 09:32 and A bearish at 09:38; no Hilega entry met the combined lifecycle filter. Inspect the exported timeline and checks for each rejected setup.

Do not activate this filter based on this sample: combined net deteriorated by 21.25 points. Full-window covered-date testing is still needed. These are reconstructed Nifty points, excluding fees, slippage and option fills; live/chart indicator parity is not established.
