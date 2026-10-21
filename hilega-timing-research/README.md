# Offline 5m / 3m comparison

Run from your RB-ITOS-AI root. No installer or service restart is needed.
The installed live policy is untouched. The three-minute variant uses isolated
copies of the same policy and canonical setup engines. All candle-duration
calculations, followup spacing, gap references and opening-path stages use 3m.
Periods RSI9, EMA3 of RSI, WMA21 and price EMA10, plus numeric thresholds,
remain unchanged. This changes their physical time horizon; it is a complete
3m variant, not five-minute indicators sampled more often.

The 5m run uses installed source, checked against uploaded-source hashes.
The 3m package imports shared dependencies from the installed backend through
an isolated package namespace. It does not patch sys.modules for market_lab.
No API/broker requests are made. Inputs and original audit files are read only.

Use the supplied input ZIP and JSON next to this directory:

```bash
PYTHONPATH=backend:. .venv/bin/python hilega-timing-research/test_timing.py
PYTHONPATH=backend:. .venv/bin/python hilega-timing-research/run.py \
  --input-zip hilega-timing-input-2026-10-21.zip \
  --session-input hilega-timing-candles-2026-10-21.json \
  --as-of 11:55 \
  --output data/research/hilega-timing-20261021-1155
```

Comparison uses the same 11:55 mark; last fully completed 3m candle ends 11:54.
Open trades are marked separately and never assigned an invented exit.
Cutoff remains 14:55; no partial 3m candle is consumed at cutoff.
Warmup is all nonempty exported sessions strictly before the target date.

Read comparison.md and report.json in the output directory. Only a PASS of
recorded entries/exits plus recorded indicator/OHLC checks supports conclusions
about performance against today's live baseline. Otherwise inspect parity issues.
The uploaded audit extract is not a complete hash chain; matching it does not
authenticate the original journal. Figures are gross NIFTY points, not option P&L.

Prepared with static review only; tests and replay execution are left to the VM.
