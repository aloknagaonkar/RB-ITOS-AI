# Hilega-Milega BULLISH_ENTRY / BULLISH_CONTINUATION / BULLISH_EXIT UI

Frontend-only cumulative patch for the existing RB-ITOS-AI **Hilega-Milega Historical Replay** and **Hilega Shadow Live** interfaces. It retains the existing ALL3 replay. If the earlier unified-table patch is not installed, this package installs its components first; if it is installed, it upgrades only the shared presentation and its tests.

## Behaviors

- Green `BULLISH_ENTRY` **on the signal candle**, never on the later option premium acquisition minute.
- Light-green `BULLISH_CONTINUATION` on subsequent completed candles whose *recorded strategy state* remains `BULLISH_ACTIVE` without a recorded exit. This is not another entry signal.
- Red `BULLISH_EXIT` when a structural/cutoff exit event is recorded. Exit takes precedence over continuation, including when exact option exit prices are still pending.
- Amber `ARMED / OPENING CANDIDATE`; muted rejected setups; neutral candles with no recorded signal.
- Preserve original Opening Path, Route A or Route B identity across available entry/continuation/exit rows; if earlier records are missing, explicitly display that entry route is unavailable. Do not carry routes across session dates or closed positions.
- Each row retains `View audit`: OHLC, previous/current RSI9/EMA3/WMA21, recorded conditions and failure reasons, lifecycle event timestamps, five independent ATM±2 CE entry/exit OPEN premiums and derived premium-points/percentage results, where the evidence exists.
- Progressive historical mode hides future checkpoints and only displays option records whose timestamps are available by the selected candle boundary. Full-session retrospective mode can show completed trade results.
- No changes to the strategy algorithm, backend, execution permissions, market-data acquisition, journal or worker process.

## Installation (VM)

Transfer ZIP to VM and from the repo root:

```bash
unzip hilega-bullish-status-ui-patch.zip -d /tmp/
cd ~/RB-ITOS-AI
source .venv/bin/activate
python /tmp/hilega-bullish-status-patch/install.py --repo "$PWD" --check
# ONLY IF CHECK PASSES
python /tmp/hilega-bullish-status-patch/install.py --repo "$PWD" --apply
node tests/test_hilega_decision_table_v1.cjs
cd frontend && npm run build
```

After the build succeeds, hard-refresh both pages in the browser. The FastAPI application serves `frontend/dist` directly, so **do not restart the API, main worker or live-shadow worker for this frontend-only change**.

## Compatibility and safeguards

The installer accepts the verified independent Hilega session component and original live page from the supplied ZIP, as well as the exact previous unified-table patch. It refuses unknown local modifications and backs up modified existing files beneath `.hilega-bullish-status-backup/<timestamp>/`. Re-running it is safe.

This patch does not make a new broker-download historical replay endpoint. Load an existing Hilega historical capture (such as September 23 d4) from the Hilega selector. There is no guaranteed completed live session in the source ZIP: verify classifications against the actual VM dataset and external chart.

### Local validation

- Standalone shared-classification, continuation-route tracking and CE-premium tests passed against the bundled prior unified-table component, using the TypeScript transpiler.
- Safe-installer check/apply/recheck passed with prior unified-table sources; dry-run passed with independent-session (pre-unified) source simulation.
- A complete VM frontend production build and real data/browser verification must still be run on the VM.
