# Midpoint V3.2 OOS-H Frozen Rule Evaluator V1

This adapter exists because the original development modules intentionally
allow only `TRAIN/OOS_A/OOS_B/OOS_C/OOS_D`.

It does **not** modify those modules.

## Leakage protection

The development `build_events()` filters rows by future outcome label.
That is acceptable for retrospective development diagnostics, but not for a
pristine final holdout.

This evaluator therefore:

1. reads the already-created OOS-H framework artifact;
2. rebuilds checkpoint rows using only structure, price features and OI;
3. explicitly deletes/ignores future outcome labels;
4. runs the existing diagnostics feature preparation;
5. loads `t3_train_only_rules` from the frozen development V3.2 artifact;
6. calls the existing frozen `observe_t1`, `score_t3`, `classify_t3`;
7. selects only `CONFIRM_CONTINUATION`;
8. calls the existing frozen exact-option `build_trade`;
9. writes an H-only economics artifact for the already-built frozen exit replay.

No threshold search, feature activation search, entry search, or exit search is performed.

## Install and test

Copy the files into the repo, then:

```bash
python -m pytest \
  tests/test_midpoint_v3_2_oos_h_frozen_rule_evaluator_v1.py -v
```

Run the existing OOS-H freeze hash check again before committing.

## Run the one-shot H frozen-rule economics

```bash
python -m market_lab.midpoint_v3_2_oos_h_frozen_rule_evaluator_v1 \
  --freeze-contract data/historical-evidence/midpoint-v3-2-oos-h-freeze-contract-v1.json \
  --frozen-state data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json \
  --framework data/historical-evidence/opening-candle-midpoint-framework-v1-1-oos-h.json \
  --positioning data/historical-evidence/positioning-oos-h.csv \
  --ohlc data/historical-evidence/option-ohlc-oos-h.csv \
  --output data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-oos-h.json
```

At this command, OOS-H structural/economic results are exposed. H is therefore
consumed as a pristine holdout.

## Then apply the previously frozen exit

```bash
python -m market_lab.midpoint_v3_2_oos_h_frozen_exit_replay_v1 \
  --freeze-contract data/historical-evidence/midpoint-v3-2-oos-h-freeze-contract-v1.json \
  --economics data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-oos-h.json \
  --ohlc data/historical-evidence/option-ohlc-oos-h.csv \
  --output data/historical-evidence/midpoint-v3-2-oos-h-frozen-exit-replay-v1.json
```

Finally:

```bash
python -m market_lab.midpoint_v3_2_oos_h_final_validation_v1 \
  --freeze-contract data/historical-evidence/midpoint-v3-2-oos-h-freeze-contract-v1.json \
  --replay data/historical-evidence/midpoint-v3-2-oos-h-frozen-exit-replay-v1.json \
  --output data/historical-evidence/midpoint-v3-2-oos-h-final-validation-v1.json
```
