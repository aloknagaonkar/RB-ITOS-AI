# Last-ten-session Upstox price research — no execution changes

Extract this folder into ~/RB-ITOS-AI. This standalone runner imports the existing
installed replay and ATM5 research helpers. It does not install or modify backend,
frontend, policies, .env, control, strategy timing or trading. No restart is needed.
No local tests, application Python, data acquisition or build were run.

## What this can and cannot validate

It pulls exact Upstox historical NIFTY and option candles plus contract catalogs and
expiry schedules. At every accepted strategy entry it freezes eleven same-side
ATM ±5 contracts and provider lot sizes. It compares exact entry-to-exit price
paths and declared fee/slippage scenarios, without selecting historical winners.

Historical candles do not carry bid/ask, depth, delta, gamma, theta or IV. This
runner cannot validate the proposed delta-based Top5 selection or its liquidity
filters. It does not estimate Greeks and call them recorded values. The report
always says TOP5_RULEBOOK_NOT_VALIDATED. We need recorded entry-time quote/Greek
snapshots, or future observation sessions, to validate that part. Ten sessions are
exploratory, not a new held-out optimal-policy proof.

## VM tests first

The ATM5 update must be installed. Run:

```bash
HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED=1 PYTHONPATH=backend:. \
  .venv/bin/python -m pytest -q hilega_last10_strike_research/tests
```

Tests use synthetic inputs without networking. They have not been run locally.

## Pull data and produce a report

The runner reads only UPSTOX_ACCESS_TOKEN from the VM process environment or .env.
Do not paste credentials into chat. It uses the analytics GET-only gateway, never
the Sandbox order transport. Expired endpoints may require Upstox Plus; entitlement
failure is reported explicitly, without switching to synthetic data.

Select the ten most recent provider sessions through Oct 13, excluding today:

```bash
HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED=1 PYTHONPATH=backend:. \
  .venv/bin/python hilega_last10_strike_research/run.py \
  --through-date 2026-10-13 \
  --round-trip-cost-rupees 0 --slippage-points-per-side 0 \
  --output-root data/research/hilega-last10-atm5-20261013-gross \
  > /tmp/hilega-last10-atm5-run.log 2>&1
```

The zeros explicitly request a gross-data diagnostic. They do not establish net
profitability. Use a new output folder for each realistic fee/slippage scenario,
with costs supplied by the operator; fees are not calculated from broker tariffs.

The script requests 28 calendar days of minute NIFTY candles and selects the last
ten nonempty provider sessions, retaining preceding sessions for indicator warmup.
A partial selected session fails replay; it is not silently replaced by an older
session. It generates isolated pending-switch replays with the 14:55 cutoff, not
live/manual-exit history, and never overwrites existing replay directories.

For each day, nearest expiry is obtained from the provider expiry schedule plus
active contract expiries; historical/active catalogs are fetched accordingly.
Only exact confirmed-entry strikes are requested. All fetched contracts are held
fixed through the strategy's actual exit. Partial candle paths stay incomplete.
Missing/ambiguous contract metadata cannot be invented; the strict comparison
retains all eleven expected rows as incomplete for that affected trade.

Upstox raw successful GET responses are cached and hashed for resumability. No
request headers or tokens are saved. The request pace is throttled, with bounded
retries for rate limits/network failures. Authentication/entitlement failures stop
the run. Failed runs are INCOMPLETE, with no successful report claim. Retry with the
same configuration to reuse cached responses; changed config/as-of date requires a
new output directory. To refresh stale empty provider responses use a new directory.

## Share results

```bash
tail -n 100 /tmp/hilega-last10-atm5-run.log
```

After a completed run, upload report.json from the output directory. It contains
all per-trade/per-strike results, fair common-eleven summaries, metadata issues and
source hashes. Both CE and PE outcomes are separate. Price estimates use exact
minute OPEN at confirmed timestamps plus the specified lag (default one minute).
These prices are not executable ask/bid fills. Profit/loss is a declared scenario.
All ten recent dates fall in the existing validation period; no policy selection
or training fit is performed. No Top5 policy is approved by this runner.

If you want today included, run after data is available on the following day using
--through-date 2026-10-14 and a new output folder. This avoids incomplete same-day
historical data and does not impose a new trading cutoff.
