# Independent strategy comparisons

Requires the combined promotion and replay UI fix already installed. No live strategy, broker, trade rules, candle data, or frozen results change.

The screenshot's 404 was coming from the older V2 artifact path. The previous frontend incorrectly reused that failure for recorded-live and V1. The patch supplies an independent comparison-metrics endpoint; records are read from their own recorded evidence, and V1/V2/combined load separately. V1 canonical presentation can survive a missing candidate presentation. Missing historical evidence remains unavailable, not zero or substituted combined results. This code dependency existed in the supplied original ZIP as well; adding the combined row exposed it rather than proving historical data was deleted.

No tests or build were run locally; run these on the Ubuntu VM:

```bash
cd ~/RB-ITOS-AI
(
set -e
unzip hilega-independent-comparison-fix.zip
.venv/bin/python hilega-independent-comparison-fix/install.py
.venv/bin/python hilega-independent-comparison-fix/install.py --apply
PYTHONPATH=backend:. .venv/bin/python -m pytest -q tests/test_hilega_independent_comparison.py tests/test_hilega_combined_replay_display.py tests/test_hilega_combined_promotion.py
npm --prefix frontend run build
bash scripts/restart_api_only.sh
)
curl -sS --get 'http://127.0.0.1:8123/api/live-shadow/hilega-historical/comparison-metrics' --data-urlencode 'session_date=2026-10-15' | .venv/bin/python -m json.tool
```

Refresh the browser with Ctrl+Shift+R. Share the endpoint output if V1 or V2 remain unavailable: it identifies missing evidence separately. The patch does not generate missing legacy research data or label legacy alignment as V1.
