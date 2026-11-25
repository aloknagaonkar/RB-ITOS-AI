# RSI two-route v2 — colour only

Version: rsi-two-route-0.4.1-colour-only-reversal.

Body-percentage and upper/lower-wick entry limits are removed from BOTH directions and BOTH routes. Candle colour remains strict: green CE / red PE. Normal Route: price beyond EMA30 High (CE) / Low (PE), correct colour, at least 2 of RSI5/9/14/21/28 >55 CE / <45 PE, plus WMA21(RSI9)>50 CE / <50 PE. WMA_bypass: price, colour and ALL five RSIs pass; WMA threshold waived. Normal Route has priority. Indicators must be available for both routes. Doji fails colour. Shape percentages are retained as optional diagnostics only, never route gates.

Qualified opposite entry independently closes existing trade then enters opposite at the same simulated boundary fill. Same-side signals retain owner. All-three exit unchanged: CE (RSI5<50 AND RSI9<50) AND WMA21(RSI9)<50 AND close<EMA30 Low; PE mirrored >50 and close>EMA30 High. Mandatory 15:30 close overrides all signals; no entry at close.

This bundle is research only. No installation into live application, service restart, broker connection, cache or journal mutation.

## Fresh VM replay

Run from RB-ITOS-AI with its existing verified target and 20-prior-session candle caches and bounded-warmup module:

```bash
.venv/bin/python -u -B rsi-two-route-v2/run.py --month 2026-11 --through 2026-11-23
```

Recomputes indicators from raw caches, compares original baseline versus updated colour-only rules, prints trades, entries/exits, points, peaks, giveback and result ZIP. Missing/invalid dates explicitly fail, output ZIP retained, process exits 2. No network acquisition. Calendar excludes known non-trading dates. 8 November uses 23 complete bars from 14:21 with no leading-minute padding. All other sessions strictly 125 bars. Simulated ordinary fills are next 1m open; terminal close exact 15:29 close. No costs or option premium fills. Summed trade peaks are not a realizable portfolio return.

Outputs under data/research/rsi-two-route-v2-<timestamp>: audit.html with date/direction/day-trend/entry-route filters; baseline-audit.html; comparison.html; results.json; daily-summary.csv, trades.csv and candle-audit.csv. Route filter applies to trades/totals, both-side candle diagnostics remain available. Day trend is descriptive full-day close versus open and never an entry filter.

## Re-evaluate the previously uploaded audit

```bash
.venv/bin/python -u -B rsi-two-route-v2/replay_from_audit.py \
  --archive data/research/rsi-two-route-20261124T081105460021.zip \
  --output /tmp/rsi-two-route-no-strength-review
```

Output folder must be new. This reuses recorded completed 3m indicator frames. Before applying the change, reproduces ALL original-baseline and strength-filter trades, ownership, events, next-open fills and excursions (32 day/model checks). It then evaluates the new entry rules with unchanged exits and reversal behavior.

No raw provider minutes or warmup files are embedded in that source ZIP: this mode does NOT independently recalculate RSI/EMA/WMA seeding. Ordinary fills are known opens of the next completed 3m frame, which equal the corresponding boundary-minute opens. Held intervals align to complete 3m bars; extrema are aggregated from their high/low without creating or claiming raw minute candles. Re-evaluation is labeled AUDIT_FRAME_REEVALUATION_PASS and distinguished from a fresh-cache replay. Original ZIP is read-only.

Reference engines baseline.py (original 0.3.0) and strength_reference.py (previous 0.4.0) are preserved for comparison and parity; neither adds entry gates to the updated engine.

## Validation

19 local tests passed: both routes/directions, every 2-RSI pair, missing/readiness/strict thresholds, large-wick acceptance, doji/colour rejection, reversal, session priority, unchanged exits and indicators, short session, HTML/JavaScript filters, supplied-frame/native replay parity, and CLI export with explicit partial failure.

Actual 1–23 November supplied-frame re-evaluation: 50 trades, 26 winners, 24 losers, net +1507.55, summed peak 4726.95, giveback 3219.40. Source strength-filter result reproduced +892.90 and original baseline +1081.60. These are sample research results, not independently verified provider data or broker execution. A fresh VM run is the raw-cache confirmation step. Live application stays unchanged.
