# ATM ±5 offline research

This adds an eleven-candidate research range only. Sandbox still uses its existing
ATM ±2 execution/observation universe; no selector, worker, policy, environment,
frontend or cutoff change is included. No local application code, tests or build
were run. Existing five-candidate research remains the default (--wings 2).

## Coverage without inventing contract metadata

scripts/research_hilega_atm5_coverage.py checks the eleven CE or PE contracts at
accepted replay entry ATM, using confirmed entry/exit timestamps. The same tie-to-
lower rule is used as the existing worker. A configurable zero/one-minute pricing
lag controls which exact option minutes are required. The path includes entry,
every intermediate minute and the exit minute. Zero-length holds are incomplete.

Each accepted trade contributes eleven expected paths, including days without
usable caches. Summaries separate CE/PE and training/validation by date, not cache
folder names. Reported complete paths are exact cached reconstruction evidence;
they are not fill evidence. A complete-all-eleven cohort is counted separately.
Identical duplicate cache rows merge; conflicting required minutes and ambiguous
instrument identities are incomplete, with no interpolation or alternate-strike
fallback. Cache filename dates and row timezones are checked on load.

The tool chooses the nearest nonexpired expiry present in usable caches. It does
not prove this is the nearest eligible expiry in the historical contract universe.
Missing historical lot sizes, bid/ask, IV and Greeks remain unverified. Expired
reconstruction keys (including expiry suffixes) must never be used for live orders.
No approved manifest is generated and no strike winner is named by this report.

## VM coverage command

Confirm the strategy version in your actual replay artifacts first. Then run:

```bash
PYTHONPATH=backend:. .venv/bin/python scripts/research_hilega_atm5_coverage.py \
  --expected-version five-minute-setup-1.2.0-pending-switch \
  --output /tmp/hilega-atm5-coverage.json
```

A compact summary is printed; full per-trade/per-role details are saved in the
specified file. If the replay version differs, do not simply bypass the check:
identify which strategy the replay represents before using its results. No API
request or Sandbox action is performed. No replay files causes an explicit error.
The report counts existing replay dates; it does not assert trading-calendar
completeness. Cache dates alone (currently 61 training and 47 validation dates in
your inventory) do not establish exact signal-time eleven-contract coverage.

Repeat with --lag-minutes 0 for a separately labelled timing sensitivity check.

## Strict price comparison after metadata verification

scripts/research_hilega_strike_ranking.py now accepts --wings 5. It still requires
historical frozen manifests with verified nearest expiry, integer historical lot
size, exact side/strike/instrument identity and matching accepted entry timestamp.
Use the existing manifest shape but supply roles -5 through +5 (eleven contracts).
Without verified metadata all expected trade rows remain incomplete.

```bash
PYTHONPATH=backend:. .venv/bin/python scripts/research_hilega_strike_ranking.py \
  --wings 5 --expected-version five-minute-setup-1.2.0-pending-switch \
  --round-trip-cost-rupees 0 --slippage-points-per-side 0 \
  > /tmp/hilega-atm5-strict-inventory.json
```

The zeros above deliberately request an inventory/gross diagnostic, not realistic
net profitability. For actual comparison supply --contract-manifest and realistic
fee/slippage scenarios. Output has candidate_count=11, expected_roles=-5..+5,
common_complete_trades, common coverage, net scenarios and adverse movement.
common_five_complete_trades is retained only for legacy five-role reports; for
wings 5 it is null. Model is HILEGA_STRIKE_COMPARISON_RESEARCH_V3.

Use common-eleven complete trades for ranking comparisons and also show broader
per-role coverage so missing outer strikes cannot create a biased winner. Current
historical periods have been used in earlier research, so validation is not a fresh
untouched holdout. Approve no strike policy from cache coverage alone.
