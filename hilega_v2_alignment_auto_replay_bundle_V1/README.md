# Automatic historical V2 alignment replay

Install from the RB-ITOS-AI project root:

```bash
source .venv/bin/activate
python hilega_v2_alignment_auto_replay_bundle/install.py &&
./scripts/restart.sh &&
./scripts/status.sh
```

In Hilega Historical Replay select “V2 — alignment setup + dual exit (research)” and any date in the existing historical selector. This replaces the five-date artifact-only restriction. No manually copied research JSON is required. The first selection calculates the date; further requests use the saved result. Full-session and step controls expose the same minute timeline, trade ledger and condition inspection. Top performance metrics describe the entire completed session, including when stepping.

Each date requires actual Nifty one-minute candles, prior-session indicator warmup and an exact 14:55 cutoff open. Missing inputs produce explicit errors. The existing date selector can list recorded sessions without candle caches; listing alone does not mean replay inputs exist. No candles are synthesized, no broker download is triggered, and unavailable or incomplete inputs are not represented as zero-trade days.

Input directories, in increasing precedence for duplicate dates:
- data/historical-evidence/hilega-milega-underlying-cache-v1
- data/recovery/october-2026/replay-input/replay-warmup
- data/recovery/october-2026/nifty-cache

Only dates earlier than the selected session warm its indicators. Different or corrected warmup inputs can change results. Candle and engine fingerprints invalidate stale results; prior research reports are preserved. Results are written only beneath data/historical-evidence/hilega-v2-alignment-dual-exit-v1. The per-date lock prevents simultaneous duplicate calculations; an HTTP 409 means retry shortly.

Rules: V1 canonical setup OR completed five-minute directional RSI9/EMA3/WMA21 ordering with a positive expanding provisional minute gap. Entries retain directional WMA change >=0.75, later consecutive-minute persistence, positive expanding gap, ten-minute window and single owner. Actual exits require both RSI9 and EMA3 opposite WMA21 at a completed five-minute close; equality waits. RSI-only crossing is an initial warning. Exit completes before a qualifying replacement entry on the same boundary. Cutoff is 14:55 IST. EMA3 and WMA21 are indicators of RSI9; this is not the five-minute price EMA10 exit experiment.

Scope: historical research only. Live strategy selection, Sandbox arming, order dispatch, quantities, original frozen evidence and forward-confirmation reports are unchanged. Reconstructed Nifty points exclude option fills, fees and slippage. Chart/live indicator parity remains unconfirmed; this does not authorize strategy promotion.

Validation: nine unittest checks cover minute integrity, future warmup exclusion, both exit conditions, exit-before-reentry, automatic calculation and cache invalidation, source precedence and specific HTTP errors. Python compilation and TypeScript/Vite production build passed. A real recovered Oct 6 run produced 341 audit rows, seven trades and -50.70 Nifty points, matching the earlier tested result. Other dates calculate from their own available inputs; they are not claimed independently verified on your VM.

The installer validates guarded source anchors, backs up replaced files, and restores source if a check fails. If a frontend build fails after starting, rebuild the restored frontend before restarting.
