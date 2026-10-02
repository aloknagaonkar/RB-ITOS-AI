# V2 / V1 Population Reconciliation V1

## Why this audit exists

The V2 structural reconstruction produced:

- 81 `IMMEDIATE_CONTINUATION`
- 8 `BASE_THEN_GO`
- 9 `FAILED_BREAK_RECLAIM`

The frozen V1 development baseline had 77 confirmed candidates.

Before option economics, reconcile the 81 vs 77 difference.

The leading hypothesis is expected:
the old development `build_events()` required historical future outcome labels
(`CONTINUATION` / `REVERSAL`) to admit an event, while the new leakage-safe V2
population deliberately does not use future labels.

This audit identifies the exact differing events.

## Important

Historical future labels are used ONLY to explain population membership.
They are NOT used to select V2 candidates.

No P&L.
No OOS-H.
No V1 modification.

## Run tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_v1_population_reconciliation_v1.py -v
```

## Run reconciliation

```bash
python -m market_lab.midpoint_v2_v1_population_reconciliation_v1 \
  --framework data/historical-evidence/opening-candle-midpoint-framework-v1-1-development.json \
  --frozen-state data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json \
  --output data/historical-evidence/midpoint-v2-v1-population-reconciliation-v1-development.json
```

## Compact output

```bash
jq '{
  research_version,
  old_labelled_population,
  leakage_safe_population,
  reconciliation,
  interpretation_guard
}' \
data/historical-evidence/midpoint-v2-v1-population-reconciliation-v1-development.json
```

## Decision rule

Do not proceed to V2 option economics until:

1. the historical V1 labelled confirmed count reconciles to the known baseline;
2. every leakage-safe extra candidate has an explicit population reason;
3. no old confirmed candidate is unexpectedly lost, or any loss is explained;
4. the audit confirms future labels are diagnostic-only.

If the four extra events are simply previously `UNRESOLVED` / non-labelled
events that now pass the frozen T+3 rules, that is a prospective-population
definition issue. We will then decide explicitly whether V2 includes them,
rather than allowing them in silently.


## Fix1

Corrected integration with the existing repo helper:

```python
outcome_label(direction, outcome)
```

The earlier bundle incorrectly passed only `outcome`.


## Fix2

Corrected variable ordering in `labelled_checkpoint_rows()`.

Wrong:

```python
label = outcome_label(direction, outcome)
direction = direction_for_event(event)
```

Correct:

```python
direction = direction_for_event(event)
if direction not in {"BULLISH", "BEARISH"}:
    continue
label = outcome_label(direction, outcome)
```

Also added a regression test exercising this code path.
