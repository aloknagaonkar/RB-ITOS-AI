MIDPOINT LIVE SIGNAL-GAP VALIDATOR V1

Folder structure after installation:

RB-ITOS-AI/
  scripts/
    validate_midpoint_signal_gap.py
  tests/
    test_validate_midpoint_signal_gap.py

Install:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_signal_gap_validator_bundle/install.py

Validate every completed minute from today's 09:15 open onward:

  PYTHONPATH=backend:. python scripts/validate_midpoint_signal_gap.py \
    --session-date 2026-10-01 \
    --from-time 09:15

This prints through the latest completed minute. Add --to-time HH:MM only when
you intentionally want an earlier cutoff.

Outputs include report.json, immutable live-events.jsonl, replay-audit.jsonl,
minute-trace.jsonl and a spreadsheet-friendly minute-trace.csv. Each minute records NIFTY OHLC,
futures OHLC/volume/VWAP, both-direction health, reference gates, active state,
rearm/PM state, emitted events and the reason no entry was emitted.

The script is read only. It does not restart services or change the live
audit, live gates, entries, exits, orders, paper orders, or quantity.
