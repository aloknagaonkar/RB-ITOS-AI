# Correct Hilega armed-candidate direction display

Presentation-only update. The VM audit on14 October reports bearish_armed=true,bullish_armed=false from09:20 through09:26, followed by bearish entry09:27 at22689.20. The screenshot labels pending rows bullish. This fix projects an explicit direction from audited owner,exclusive pending flags and recorded confirmation-check evidence; the frontend also prioritizes exclusive armed flags over stale/default pending direction. Active owner and exit direction remain authoritative.

No strategy,setup,confirmation,persistence,expiry,orders,prices or audit records are changed. Minute monitoring remains minute monitoring. All9 uploaded decision rows resolve BEARISH;9 API/helper checks and15 renderer checks passed. Renderer tests execute the real direction function with its TypeScript annotations removed for Node evaluation. Full TypeScript/Vite build is required on the deployed VM; frontend dependencies were unavailable in this container, so a full local build was not performed.

## Install from RB-ITOS-AI root

```bash
tar -xzf hilega-pending-direction-label-fix.tar.gz
source .venv/bin/activate
python hilega_pending_label_fix/install.py --check
python hilega_pending_label_fix/install.py
python hilega_pending_label_fix/test_projection.py .
node hilega_pending_label_fix/test_display.cjs .
npm --prefix frontend run build
bash scripts/restart_api_only.sh
```

Only continue with API restart after the frontend build succeeds. Then refresh the browser with Ctrl+F5. The installer validates exact source anchors and creates backups under backups/hilega-pending-label-TIMESTAMP before editing. It adds backend/market_lab/hilega_pending_direction_display_v1.py, patches the directional report projection in hilega_historical_ui_api_v1.py and inserts pending-direction safeguards in frontend/src/hilegaDecisionTable.tsx. It preserves other source changes and supports reapplication. If anchors differ, it stops without editing. Existing historical audit evidence is not rewritten; corrected labels derive from existing recorded flags.

The API-only restart avoids restarting the live-shadow and Sandbox workers. No full application restart or trading-rule deployment is required.

## Verify

For14 October:
-09:20–09:26: BEARISH · ARMED / CANDIDATE and BEARISH_CANDIDATE / ARMED.
-09:27: BEARISH ENTRY, unchanged price22689.20.
-09:30: BEARISH continuation, unchanged recorded trade data.

If the browser still shows bullish after API restart and hard refresh, capture that row's returned strategy.direction, bullish_armed,bearish_armed and current loaded UI bundle name. Runtime VM source version and assets have not been inspected directly from this chat.
