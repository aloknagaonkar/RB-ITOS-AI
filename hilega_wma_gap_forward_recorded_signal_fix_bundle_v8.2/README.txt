Hilega WMA-gap forward recorded-signal correction V8.2

Revision V8.1: accepts both historical ``Bar.ts`` and forward-cache
``Bar.timestamp`` representations during recorded lifecycle valuation.

Revision V8.2: writes the complete canonical cache envelope (schema version,
underlying and session date). It also detects and replaces the earlier
simplified cache that the indicator validator could read but canonical replay
correctly rejected.

Problem fixed
-------------
The 2026-10-05 forward session was incorrectly published as zero-trade because
the final revised-candle replay produced zero entries, although immutable live
evidence recorded 8 entries and 7 completed trades.

Correct rule
------------
* New forward-confirmation signals and completed lifecycles come from the
  immutable recorded-live decision audit.
* Final revised-candle replay remains a parity diagnostic only.
* WMA-gap V2 evaluates every completed recorded-live trade minute by minute.
* An unresolved recorded-live signal is reported but not valued as a trade.
* The old session artifact is moved to superseded/ before rebuilding.

Install
-------
python hilega_wma_gap_forward_recorded_signal_fix_bundle_v8.2/install.py

Rebuild October 5
-----------------
./scripts/stop_hilega_wma_gap_forward_publisher.sh

PYTHONPATH=backend:. python scripts/hilega_wma_gap_forward_publisher.py \
  --rebuild-date 2026-10-05 \
  --confirm REBUILD_FORWARD_SESSION

./scripts/restart.sh
./scripts/status.sh

Verify
------
curl -fsS 'http://127.0.0.1:8123/api/live-shadow/hilega-historical/strategy-test?session_date=2026-10-05' | python -m json.tool

Expected: reports > 0, V1 completed=7, and V2 contains signal/wait/entry-or-denial/
exit audit rows. Forward eligibility remains fail-closed if unresolved/parity
evidence still differs.

Safety
------
Observation only. No live strategy, broker order, paper-order gate, quantity,
or frozen 490-session evidence is changed.
