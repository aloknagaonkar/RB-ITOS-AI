"""Acquire exact Midpoint options to a separate tape; run after market hours.

PYTHONPATH=backend python -m market_lab.midpoint_strategy.materialize_option_observation \
  --session-date 2026-09-29 --expiry YYYY-MM-DD

Requires the existing UPSTOX_ACCESS_TOKEN. Does not start a worker or order.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from market_lab.midpoint_strategy.option_observation import create_tape
from market_lab.midpoint_strategy.replay import load_audit_jsonl
from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
from market_lab.domain import IST

AUDIT = Path("data/live-observation/midpoint-strategy-v1/audit.jsonl")
OUT = Path("data/live-observation/midpoint-strategy-v1/option-observation")
UNDERLYING = "NSE_INDEX|Nifty 50"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-date", required=True, type=date.fromisoformat)
    parser.add_argument("--expiry", required=True, type=date.fromisoformat,
                        help="Exact expiry known at entry; never infer a past expiry from today's catalog")
    args = parser.parse_args()
    load_dotenv(".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit("UPSTOX_ACCESS_TOKEN is required")
    rows = [r for r in load_audit_jsonl(AUDIT) if r.get("session_date") == args.session_date.isoformat()]
    entries = [
        r for r in rows
        if r.get("event_type") in {
            "B_ENTRY", "E_ENTRY", "B_REARM_ENTRY", "E_REARM_ENTRY"
        }
    ]
    if not entries:
        raise SystemExit("No Midpoint B/E entry audit for this date")
    sources = UpstoxLiveShadowSourcesV1(token)
    try:
        contracts = sources.option_contracts(UNDERLYING, args.expiry)
        candles = {}

        def exact_minutes(key):
            if key not in candles:
                # Upstox can return an empty historical collection on the
                # current session even after market close. Use its exact 1m
                # intraday endpoint for that session only.
                if args.session_date == datetime.now(IST).date():
                    rows = sources.option_intraday_1m(key)
                else:
                    rows = sources.historical_candles(key, args.session_date)
                candles[key] = [row for row in rows
                                if row.timestamp.astimezone(IST).date() == args.session_date]
            return candles[key]

        tapes = []
        for entry in entries:
            terminal = next((r for r in rows if r.get("event_type") == "STRUCTURAL_TERMINAL"
                             and r.get("direction") == entry.get("direction")
                             and r.get("family") == entry.get("family")
                             and r.get("event_timestamp", "") >= entry["event_timestamp"]), None)
            tapes.append(create_tape(entry, terminal, expiry=args.expiry,
                                     contracts=contracts, option_minutes=exact_minutes))
        payload = {"model": "MIDPOINT_EXACT_OPTION_SESSION_V1", "session_date": args.session_date.isoformat(),
                   "tapes": tapes, "observation_only": True, "execution_enabled": False,
                   "paper_order_enabled": False, "quantity": None}
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{args.session_date.isoformat()}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True))
        temporary.replace(path)
        print(f"Saved {len(tapes)} exact option tape(s): {path}")
        for tape in tapes:
            print(tape["entry_timestamp"], tape["side"], tape["candidate_status"],
                  len(tape["legs"]), "contracts")
    finally:
        sources.close()


if __name__ == "__main__":
    main()
