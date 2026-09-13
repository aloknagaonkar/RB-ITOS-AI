# MIDPOINT V2 Structural Reconstruction V1 — Fix1

This patch preserves classification and adds explicit confirmation-time metadata
needed before exact-option economics.

For direct new-arm confirmations:

```text
absolute_confirmation_bar_index = v2_result.confirmation_bar_index
```

For a chained path:

```text
WAIT_BASE
→ boundary reclaim at start index S
→ FAILED_BREAK_RECLAIM confirms at relative index R
```

the absolute confirmation index is:

```text
S + R
```

and:

```text
confirmation_timestamp = T3 + (absolute_index + 1 minute)
```

## Linux commands

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python apply_midpoint_v2_structural_reconstruction_v1_fix1.py

python -m pytest \
  tests/test_midpoint_v2_research_foundation_v1.py \
  tests/test_midpoint_v2_structural_reconstruction_v1.py \
  tests/test_midpoint_v2_structural_confirmation_timestamp_fix1.py -v
```

Then rerun the same structural reconstruction command used previously.

Inspect the 17 new-arm candidates:

```bash
jq '[
  .rows[]
  | select(.v2_result.entry_arm == "BASE_THEN_GO"
        or .v2_result.entry_arm == "FAILED_BREAK_RECLAIM")
  | {
      block,
      session_date,
      original_direction: .direction,
      entry_arm: .v2_result.entry_arm,
      entry_direction: .v2_result.entry_direction,
      t3_timestamp,
      pre_chain_result,
      chained_reclaim_start_bar_index,
      absolute_confirmation_bar_index,
      confirmation_timestamp
    }
]' \
data/historical-evidence/midpoint-v2-structural-reconstruction-v1-development.json
```

Expected counts must remain unchanged:

- BASE_THEN_GO = 8
- FAILED_BREAK_RECLAIM = 9
- IMMEDIATE_CONTINUATION = 81

Do not run option economics until all 17 new-arm rows have non-null
`confirmation_timestamp`.
