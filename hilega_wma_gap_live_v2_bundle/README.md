# WMA-gap V2 live shadow and five-leg Upstox Sandbox

This patch selects `HILEGA_WMA_GAP_V2_LIVE_SHADOW` instead of V1 in `.env` after validation passes. V1 source and historical records remain available. V1 canonical engines continue supplying V2's setup and structural-exit predicates internally; they do not submit an independent V1 trade stream.

## Rules

| Step | V2 behaviour |
|---|---|
| Setup | Canonical Hilega bullish/bearish setup from completed five-minute candles |
| Indicator chain | RSI9, EMA3 of RSI9, WMA21 of RSI9; provisional one-minute observations clone the last completed five-minute indicator state |
| WMA strength | Bullish current minus reference WMA21; bearish reference minus current WMA21; threshold >=0.75 |
| Confirmation window | Ten completed one-minute observations following canonical signal availability |
| Ordinary entry | Arm on qualifying WMA strength; confirm on a later adjacent minute with both WMA strengths >=0.75, positive directional gap, and gap expansion >0 |
| Directional gap | Bullish EMA3 minus WMA21; bearish WMA21 minus EMA3 |
| Previous observation | Actual immediately preceding completed minute, using its own causal reference state; always displayed when available |
| Existing structural exit | Bullish RSI9 crosses below WMA21; bearish RSI9 crosses above WMA21 |
| Same exit boundary | Close existing V2 owner first; accept a newly qualified canonical setup on that boundary if both adjacent minutes satisfy WMA strength, current gap is positive and expanding, and ownership is free |
| Incomplete confirmation at exit | Preserve setup waiting/armed; evaluate subsequent completed minutes within the confirmation window |
| Session cutoff | Exact 14:55 Nifty OPEN; no replacement entry at/after that boundary |
| Sandbox basket | Five actual sandbox option BUY requests, ATM +/-2; exits SELL the original stored contracts and quantities |
| Sandbox ordering | All previous basket SELL responses must be acknowledged before replacement BUYs; any uncertain response blocks replacement entry |
| Expiry | Existing automatic nearest eligible expiry selection; five contiguous strikes and broker lot sizes |

Same-boundary confirmation is a NEW entry-policy variant: it can use the completed minute preceding canonical setup availability. Ordinary entries still require a post-arm later minute. The earlier 490-session research does not establish the profitability of this new sequential variant. EMA10 is not enabled.

EMA continuation and RSI/EMA/WMA alignment appear as diagnostic values; they are not new entry gates. Missing, duplicate or nonconsecutive minute evidence cannot pass confirmation. Prices used for V2 underlying entry are completed-minute closes, available at the following minute boundary; this corrects reporting availability without backdating broker submission.

## Install from repository root

Download the ZIP into `~/RB-ITOS-AI`, then:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
./scripts/stop_hilega_upstox_sandbox_worker.sh
PYTHONPATH=backend:. python -m market_lab.hilega_upstox_sandbox_basket_v2 --disarm
unzip -o hilega_wma_gap_live_v2_bundle.zip
python hilega_wma_gap_live_v2_bundle/install.py &&
./scripts/restart.sh &&
./scripts/status.sh
```

If you previously exported `LIVE_SHADOW_STRATEGY`, run `unset LIVE_SHADOW_STRATEGY` BEFORE installing/restarting so the new `.env` selection is used.

The installer verifies source hashes against your uploaded ZIP (or the already installed patch), backs up modified source and frontend dist, runs tests/compilation/frontend build, and only then changes strategy selection. No tokens are printed. It stops if the source differs or an open/uncertain Sandbox position requires reconciliation. It does not start or arm a broker worker.

## Arm the next market session

For 9 October 2026:

```bash
PYTHONPATH=backend:. python -m market_lab.hilega_upstox_sandbox_basket_v2 \
  --arm-session 2026-10-09 --confirm ARM_UPSTOX_SANDBOX_FIVE_LEGS
./scripts/start_hilega_upstox_sandbox_worker.sh
./scripts/status_hilega_upstox_sandbox_worker.sh
```

Use the intended session date on later days. Existing Sandbox execution gates/tokens must be configured. There is no daily order-count cap. Arming requires reconciliation of existing positions/unknown requests and records a source-sequence baseline; old signals are not backfilled into orders. Actual broker fill prices are not inferred from acknowledgements. Dashboard P&L retains its existing quote-based estimate labels.

## Verify selection and inspection

```bash
curl -fsS 'http://127.0.0.1:8123/api/live-shadow/hilega-directional/status?fast=true' \
  -o /tmp/hilega-v2-status.json
python - <<'PY'
import json
x=json.load(open('/tmp/hilega-v2-status.json'))
print('Selected:', x.get('selected_live_shadow_strategy'))
print('Directional active:', x.get('directional_mode_active'))
print('Current:', x.get('current'))
PY
```

Expected selection: `HILEGA_WMA_GAP_V2_LIVE_SHADOW`; directional active: true. In the Hilega live workspace, the top banner shows this identifier. The new **WMA-gap V2 minute decision audit** shows prior/current gap, expansion, both WMA strengths, persistence and reason. The existing Sandbox dashboard shows five active legs and quote-based P&L.

Audit source remains the existing append-only directional journal. Every new V2 row carries its strategy identifier. The bridge isolates strategy histories, accepts an explicit V2 EXIT+ENTRY pair in one record, orders exits first, and continues rejecting ambiguous multiple entries. Historical V1 accepted events cannot be dispatched under V2's selected strategy.

The existing V1-control forward-confirmation publisher is guarded on sessions with processed V2 live decisions: it reports `V2_LIVE_POLICY_REQUIRES_SEPARATE_FORWARD_COHORT` instead of relabelling V2 trades as canonical V1. Existing frozen/forward records are preserved. Automatic publication of the new policy into a separately versioned V2 cohort is not included in this bundle; current V2 decisions remain available in the live audit and Sandbox dashboard.

Restart recovery reconstructs V2 strategy state from historical minutes but does not submit recovered entries or reselect historical option contracts. Only previously audited V2 option identities can be restored. A missing minute reports waiting and resumes when exact evidence arrives. Each new session resets owner, pending setups and locks while warming indicator history.

## Validation

Targeted pytest suite, Python compilation and TypeScript/Vite build were run locally with mocked market and broker scenarios; no broker calls were made. Installer reruns validation in your VM's Python environment. A real-session end-to-end validation remains necessary after activation.

## Roll back selection

Stop/disarm the Sandbox worker with no open/uncertain basket, set `LIVE_SHADOW_STRATEGY=HILEGA_DIRECTIONAL_SHADOW_V1` in `.env`, then restart. Historical data is not deleted. The installer prints the local backup path for source rollback if needed.
