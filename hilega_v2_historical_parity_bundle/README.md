# Historical V2 policy alignment

Aligns live V2 with the frozen 490-session ordered-gap policy: canonical V1 coordinator, no actual entry on an exit boundary, first eligible observation after signal close, 0.75 strength on two consecutive eligible observations, positive expanding gap, ten-minute window, existing structural exit and 14:55 cutoff. The former same-boundary reversal extension is disabled. Arming is still preserved where canonical V1 permits it.

Keeps canonical setup/ownership/conditions separate from actual V2 position in audit diagnostics. Includes minute audit and bearish points corrections. No EMA10, PCR, or first-touch entry rule is introduced. The frozen 490 sessions are not rebuilt.

Historical entry timestamp is the observed minute label; live execution is only possible after that minute closes, one minute later. Prices use the same observed close. Sandbox acknowledgements and option quote prices are separate from Nifty backtest P&L.

Install after market close, from repository root:
```
source .venv/bin/activate
python hilega_v2_historical_parity_bundle/install.py && ./scripts/restart.sh && ./scripts/status.sh
```
The installer backs up changed files and restores source if validation fails. Refresh browser afterward. Sandbox remains separately session-armed; no installer broker calls occur.

Validation: deterministic gate compared with historical ordered_gap_confirmation over synthetic bullish/bearish minute traces and actual Oct 9 audit windows. Frontend build checked separately. A full 490-session indicator parity rerun is not claimed: previously identified Sep 25 cache/frozen drift needs separate resolution.
