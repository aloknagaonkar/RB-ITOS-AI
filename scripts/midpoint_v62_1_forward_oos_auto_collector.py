#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from market_lab.midpoint_strategy.forward_oos_v62_1 import MidpointV621ForwardOOSCollector

DEFAULT_LEDGER = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-v62-forward-reentry-oos/reentry-oos-ledger-v62.csv"
)

def tail_jsonl(path: Path, start_at_end: bool):
    with path.open() as fh:
        if start_at_end:
            fh.seek(0, 2)
        while True:
            line = fh.readline()
            if not line:
                time.sleep(0.25)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stream-jsonl", type=Path, required=True,
                   help="JSONL stream containing audit events and completed 1m candles")
    p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    p.add_argument("--from-start", action="store_true",
                   help="Replay existing stream content; default is new lines only")
    args = p.parse_args()

    c = MidpointV621ForwardOOSCollector(args.ledger)

    print("MIDPOINT V62.1 — FORWARD OOS AUTO COLLECTOR")
    print("observation/research only; no orders; no strategy mutation")
    print(f"stream={args.stream_jsonl}")
    print(f"ledger={args.ledger}")

    for item in tail_jsonl(args.stream_jsonl, start_at_end=not args.from_start):
        kind = item.get("kind") or item.get("record_type")

        # Adapter contract:
        # {"kind":"audit","event":{...}}
        # {"kind":"candle","timestamp":...,"high":...,"low":...,"close":...}
        if kind == "audit":
            ev = item.get("event") or {}
            c.on_audit_event(ev)
        elif kind == "candle":
            try:
                c.on_completed_underlying_candle(
                    timestamp=item["timestamp"],
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                )
            except Exception:
                continue

if __name__ == "__main__":
    main()
