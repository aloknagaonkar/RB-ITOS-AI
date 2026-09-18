# Historical Replay Compatibility Probe V1

Purpose: lock the exact current interfaces before writing the one-day replay runner.

Earlier live-shadow work exposed an important production-only mismatch (`candle1_timestamp`
versus `all3_candle1_timestamp`). The replay engine must therefore not guess current
constructor or market-source method signatures.

This probe is read-only. It:
- imports the current production shadow modules
- records class/method signatures
- records the exact coordinator source
- extracts calls made through source/market-source attributes
- writes one JSON report under the replay area
- changes no strategy, live-shadow event file, broker, paper-order, or execution setting

Run:

`python -m market_lab.historical_replay_compat_probe_v1 > /tmp/replay-compat.txt`

Then:

`cat data/live-observation/replay/compat-probe-v1.json`

The report is the compatibility gate for Historical Replay Engine V1.
