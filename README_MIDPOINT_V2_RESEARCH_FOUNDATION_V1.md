# MIDPOINT V2 Research Foundation V1

This bundle starts V2 without changing frozen V1.

## Run tests
```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest \
  tests/test_midpoint_v2_research_foundation_v1.py \
  tests/test_midpoint_v2_exit_duration_research_v1.py -v
```

## Verify V1 freeze
Run the same existing V1 freeze hash check. Do not modify hashed V1 modules.

## Run development schema probe
```bash
python -m market_lab.midpoint_v2_development_schema_probe_v1 \
  --framework data/historical-evidence/opening-candle-midpoint-framework-v1-1-development.json \
  --output data/historical-evidence/midpoint-v2-development-schema-probe-v1.json
```

Then:
```bash
jq '{research_version,event_count,blocks,forbidden_blocks_present,candidate_paths,governance}' \
  data/historical-evidence/midpoint-v2-development-schema-probe-v1.json
```

Do NOT run this on OOS-H.

After the schema probe, wire V2 historical reconstruction against the actual framework field names, then collect structural counts before any P&L-based selection.
