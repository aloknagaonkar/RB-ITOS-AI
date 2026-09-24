# Hilega bootstrap recovered-checkpoints patch

Purpose:
Prevent a live-shadow worker restart from silently hiding a completed current-day
5-minute strategy checkpoint.

Behavior:
- Historical warmup sessions remain silent.
- Current-day completed bars replay through the canonical strategy into an in-memory collector.
- The patch checks the append-only step audit for already-recorded STRATEGY_DECISION checkpoints.
- Only missing current-day checkpoints are appended to the real audit.
- Recovered rows use the real replay-computed indicator/decision/transition payloads.
- Each recovered checkpoint also receives `BOOTSTRAP_RECOVERED_CHECKPOINT`.
- Existing rows are not rewritten or duplicated.

Operational note:
This is coordinator/worker code. Do not restart the live-shadow worker during market hours
just to install it. It can be applied to disk and activated at the next intentional worker restart.
