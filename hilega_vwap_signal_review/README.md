# Current HILEGA signals with VWAP context

Run from repository root on the VM. No local execution/tests were performed.
This independent script makes only GET calls using the existing token; no token
is printed or saved. No strategy, worker, arming, entry, exit or UI files change.

```bash
PYTHONPATH=backend:. .venv/bin/python hilega_vwap_signal_review/collect.py
```

Upload `data/research/hilega-vwap-oct13-14/report.json` for the comparison.
`signals.csv` contains setup and confirmed-entry rows with above/below/at VWAP,
distance, timing evidence, and known NIFTY trade points. Manual-exit trade points
remain unavailable. Original live records are preferred over recovery copies.

The existing source calculates NIFTY futures VWAP from cumulative volume-weighted
five-minute typical prices `(H+L+C)/3`, restarting at 09:15. This is a candle
proxy, not a tick-exact index VWAP. The index audit contains zero volume, so it
cannot establish index VWAP. The comparison uses futures close vs the same
futures contract's VWAP; NIFTY signal prices remain a separately labelled field.

Only fully completed candles are used, with every interval since 09:15 required.
For a 09:27 entry, the last eligible five-minute candle completes at 09:25.
The CSV records its age; no later candle is used retrospectively. Session candles
may have been revised by the provider after the live signal; this is reconstructed
research evidence. Current active front-contract catalog is used, suitable for
these recent October dates; older/expired sessions require historical manifests.

No VWAP entry restriction is enabled. Above VWAP agrees with bullish direction;
below agrees with bearish direction; equality is neutral. This is descriptive,
not proof that filtering will improve returns. The full day-by-day report still
requires successful data acquisition on the VM.

For future live observation, start a separate process:

```bash
PYTHONPATH=backend:. .venv/bin/python hilega_vwap_signal_review/collect.py \
  --watch --output data/live-observation/hilega-vwap-signal-v1
```

Without explicit dates, watch mode follows the current IST date, polls every
60 seconds and records errors separately. An exclusive lock prevents overlapping
writers. The append-only journal preserves each signal's first available annotation.
Initial startup may reconstruct already-existing signals; these are not guaranteed
signal-time live snapshots. No supervisor/startup script is installed automatically.
Do not run it inside the trading callback. To stop, use Ctrl-C or stop its independent
supervisor; Sandbox stays unaffected. The journal/CSV/report are file outputs;
VWAP columns are not yet added to the frontend dashboard.
