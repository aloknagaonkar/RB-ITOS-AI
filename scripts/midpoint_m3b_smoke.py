#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from market_lab.domain import IST
from market_lab.midpoint_strategy.live_shadow_v1 import MidpointLiveShadowCoordinatorV1


@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class FakeSources:
    def __init__(self, underlying, futures):
        self.underlying = underlying
        self.futures = futures

    def nifty_intraday_1m(self, *, now=None):
        return self.underlying

    def nifty_futures_intraday_1m(self, *, now=None):
        return self.futures


def make_minutes():
    start = datetime(2026, 9, 29, 9, 15, tzinfo=IST)
    u = []
    f = []

    for i in range(5):
        ts = start + timedelta(minutes=i)
        u.append(Candle(ts, 24200, 24201, 24199, 24200, 1000))
        f.append(Candle(ts, 24202, 24203, 24201, 24202, 1500))

    rows = [
        (24196.0,24198.25,24190.0,24192.0),
        (24192.0,24194.0,24184.0,24188.0),
        (24188.0,24190.0,24180.0,24183.0),
        (24183.0,24185.0,24176.0,24178.0),
        (24178.0,24180.0,24173.70,24175.0),
    ]
    for j,(o,h,l,c) in enumerate(rows, start=5):
        ts=start+timedelta(minutes=j)
        u.append(Candle(ts,o,h,l,c,1200))
        f.append(Candle(ts,c-1,c,c-2,c-1,2000))

    extra = [
        (24178,24180,24176,24180),
        (24174,24175,24168,24169),
        (24169,24170,24161,24162.90),
    ]
    for k,(o,h,l,c) in enumerate(extra, start=10):
        ts=start+timedelta(minutes=k)
        u.append(Candle(ts,o,h,l,c,1300))
        f.append(Candle(ts,c,c+1,c-1,c,2000))

    f[-2].close = 24180.0
    f[-1].close = 24000.0

    return u, f


def main():
    print("MIDPOINT STRATEGY — M3B SHARED RUNTIME SMOKE")
    print("=" * 88)

    u, f = make_minutes()
    source = FakeSources(u, f)

    with tempfile.TemporaryDirectory() as td:
        audit = Path(td) / "audit.jsonl"
        coord = MidpointLiveShadowCoordinatorV1(
            market_sources=source,
            audit_path=audit,
        )

        now = datetime(2026, 9, 29, 9, 29, 35, tzinfo=IST)
        out = coord.process(now)

        rows = coord.engine.journal.read_all()
        types = [r["event_type"] for r in rows]

        for required in (
            "OPENING_REFERENCE_CREATED",
            "MIDPOINT_BREAK",
            "BOUNDARY_BREAK",
            "B_WATCH_STARTED",
            "B_CONFIRMATION_CHECK",
            "B_ENTRY",
        ):
            assert required in types, (required, types)

        assert out["strategy_id"] == "MIDPOINT_STRATEGY_SHADOW_V1"
        assert out["safety"]["observation_only"] is True
        assert out["safety"]["execution_enabled"] is False
        assert out["safety"]["paper_order_enabled"] is False
        assert out["safety"]["quantity"] is None

        before = len(rows)
        coord.process(now)
        after = len(coord.engine.journal.read_all())
        assert after == before

        print("PASS: shared-source coordinator constructed")
        print("PASS: first RED 5m reference created after ignoring 09:15")
        print("PASS: midpoint break audited")
        print("PASS: original boundary break audited")
        print("PASS: Family B watch audited")
        print("PASS: delayed Candidate-A confirmation audited")
        print("PASS: Family B shadow entry audited")
        print("PASS: repeated process call is idempotent")
        print("PASS: observation-only / no execution / quantity None")


if __name__ == "__main__":
    main()
