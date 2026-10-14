# Historical moving/fixed ATM support for tested V2

Read-only diagnostic for October 6–9. No installation, restart, strategy change, collector enablement or order calls. The existing local API must be running.

The script joins each completed V2 trade's SIGNAL and ENTRY timestamp to the existing persisted PCR context. It reads the original baseline monthly validation trades.csv, not the time-filter candidate. Default positioning horizon is five minutes (300 seconds), maximum observation age 120 seconds. No browser is needed.

## Run

Extract this folder beside backend and scripts in RB-ITOS-AI:

```bash
cd ~/RB-ITOS-AI
.venv/bin/python hilega_pcr_signal_support_validation/run.py --self-test
.venv/bin/python hilega_pcr_signal_support_validation/run.py
```

The default trade input is:
`data/historical-evidence/hilega-v2-monthly-validation-v1/trades.csv`

Output:
`data/historical-evidence/hilega-pcr-signal-support-oct6-9-v1`

Use `--trades PATH` for another baseline trade CSV, and `--output-root PATH` for a fresh output folder. Existing outputs are preserved.

## What is measured

- Moving ATM ±5: 11 current basket strikes, CE and PE.
- Fixed ATM ±5: 11 strikes around the captured fixed center.
- PCR = total PE OI / total CE OI.
- CE/PE positioning and OI percentage changes use the installed same-instrument, same-expiry positioning implementation.
- Combined bias uses the existing absolute OI-change weighted directional votes, with 60% dominance, not an invented PCR threshold.
- SIGNAL and ENTRY are measured separately; their records must not be summed as separate trades.
- Support categories: both support, fixed support only, moving support only, conflicting bullish/bearish directions, both oppose, neither support, unavailable.
- Comparison includes winners and losers in every support group. A high PCR is not automatically bullish confirmation.

## Availability and validity

The existing context endpoint enforces provider and same-session joins and checks baseline persistence availability. The runner additionally rejects future/stale observations, expired contracts, incomplete baskets, non-contiguous strikes, missing instrument identities, missing baseline price/OI and invalid baseline timestamps. It requires expected=received=22 contracts and 11 distinct centered strikes in each panel.

Moving OI changes compare the same option instruments across the installed comparison horizon. They do not subtract unrelated old/new ATM baskets. Fixed center changes across queried timestamps for the same date/expiry are flagged unavailable. Exact morning anchor capture time is NOT independently verified by this endpoint; do not claim the 09:20 anchor was validated from this report.

Classification describes option positioning, not proof of who bought/sold or a guaranteed market direction. This method is diagnostic and has not been enabled as a Hilega filter.

## Outputs

- trade-support.csv: direction, signal/entry/exit times, Nifty points, fixed/moving ATM, expiry, PCR, CE/PE positioning, OI percentage changes, combined biases, support category, source observation and unavailable reason.
- summary.csv: counts, winners/losers, gains/losses, net and gain/loss ratio by support group, stage and direction.
- coverage.csv: date-wise counts of available fixed/moving panels and unavailable comparisons.
- contexts.json: exact API responses, including individual strike records, for manual verification.
- report.json: horizon, age limit, input hash, summary, coverage and API errors.

The existing baseline has 20 completed trades across October 6–9. This join covers those trades' signals, not every rejected or unentered V2 setup. A full rejected-signal extension needs the sessions' audit JSON.

Historical observation coverage is not guaranteed. If collection began October 9, earlier dates may be unavailable. Running now cannot recreate observations that were not captured. No historical option OI is downloaded or synthesized. Recovered Nifty/futures candles alone cannot produce option positioning. API errors must be resolved before interpreting unavailable results as absence of market data.

No local market-data outcome is included: the VM's stored PCR observations must be queried to obtain actual results. Eight synthetic validation tests passed; they test the join and guards, not profitability.
