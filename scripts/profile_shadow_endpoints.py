#!/usr/bin/env python3
"""Read-only latency/size profile for local observation dashboards."""
from __future__ import annotations

import argparse
import json
import statistics
import time
from urllib.request import urlopen

PATHS = {
    "state": "/api/state?history_limit=1",
    "midpoint": "/api/live-shadow/midpoint-strategy/status",
    "hilega_fast_status": "/api/live-shadow/hilega-directional/status?fast=true",
    "hilega_fast_candles": "/api/live-shadow/hilega-directional-candles/live?audit_only=true",
    "hilega_trades": "/api/live-shadow/hilega-directional/trade-dashboard",
    "hilega_audit": "/api/live-shadow/hilega-milega/audit-index?limit=200",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8123")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if not 1 <= args.samples <= 100:
        parser.error("samples must be 1..100")
    result = {}
    for name, path in PATHS.items():
        timings, sizes, failures = [], [], []
        for _ in range(args.samples):
            begin = time.perf_counter()
            try:
                with urlopen(args.base + path, timeout=args.timeout) as response:
                    payload = response.read()
                    if response.status != 200:
                        raise ValueError(f"HTTP {response.status}")
                timings.append(time.perf_counter() - begin)
                sizes.append(len(payload))
            except Exception as exc:
                failures.append(type(exc).__name__)
        ordered = sorted(timings)
        result[name] = {
            "path": path, "samples": len(timings), "failures": failures,
            "p50_seconds": round(statistics.median(ordered), 3) if ordered else None,
            "p95_seconds": round(ordered[max(0, int(.95 * len(ordered) + .999) - 1)], 3) if ordered else None,
            "max_bytes": max(sizes) if sizes else None,
        }
    report = json.dumps(result, indent=2)
    print(report)
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
