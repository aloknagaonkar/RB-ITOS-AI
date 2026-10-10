# All-strategy historical replay metrics correction

Requires the V2 shared replay UI correction. Install from RB-ITOS-AI root:

```bash
source .venv/bin/activate
unzip -o hilega_replay_all_strategy_metrics_bundle.zip
python hilega_replay_all_strategy_metrics_bundle/install.py &&
./scripts/restart.sh &&
./scripts/status.sh
```

Refresh the browser. Every strategy selection now assembles four same-session performance rows: recorded Live, canonical Hilega v1, original WMA-gap v2, and tested V2 alignment/dual exit. Independent metric requests do not overwrite the selected strategy's audits, trades or rule version. The selected response takes precedence for its own metrics. Other dates are rejected by the summary merge.

Missing baseline evidence or missing tested-replay candle/warmup inputs are marked unavailable with the request error, not zero P&L. Zero-trade complete results remain available; undefined win rate/profit factor renders a dash, and infinity is reserved for positive gains with no losses.

The tested replay may calculate/cache a completed date on first load, as requested by the all-strategy summary. No broker calls or live strategy changes are added. Existing replay API paths and cache remain unchanged. Frontend only.

Validation: Node checks for all-four population with either baseline or tested selection, unavailable/error labels, same-date isolation, selected response priority and true zero-trade results. TypeScript/Vite production build passed. VM/browser runtime requires validation after installation.

Installer accepts the prior shared UI version or its own version; stops on unexpected source changes, backs up replaced source and restores on failure. Rebuild restored frontend before restart if compilation fails.
