# MIDPOINT_GLOBAL_EXEMPLAR_FEATURE_SEPARATION_V1

Uses the completed 184-event global artifact and asks:

- What separates strong bullish trades from bullish failures?
- What separates strong bearish trades from bearish failures?
- What separates accepted winners from accepted losers?
- What separates rejected winners from rejected losers?

This is descriptive only. No thresholds are tuned and no rules are changed.

## Run

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_global_exemplar_feature_separation_v1.py -v

python -m market_lab.midpoint_global_exemplar_feature_separation_v1 \
  --global-analysis data/historical-evidence/midpoint-global-session-exemplar-analysis-v1-development.json \
  --output data/historical-evidence/midpoint-global-exemplar-feature-separation-v1-development.json
```

Inspect:

```bash
jq '{
  population,
  comparisons: {
    bullish: .comparisons.bullish_good_vs_bullish_failures,
    bearish: .comparisons.bearish_good_vs_bearish_failures,
    accepted: .comparisons.accepted_winners_vs_accepted_losers,
    rejected: .comparisons.rejected_winners_vs_rejected_losers
  },
  accepted_top_winners,
  accepted_worst_losers,
  rejected_top_winners,
  sep7,
  integrity,
  interpretation_guard
}' \
data/historical-evidence/midpoint-global-exemplar-feature-separation-v1-development.json
```
