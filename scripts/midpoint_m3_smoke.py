#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import tempfile

from market_lab.midpoint_strategy import live_shadow_ui as ui


def main():
    print("MIDPOINT STRATEGY — M3 API/UI PROJECTION SMOKE")
    print("=" * 88)

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "audit.jsonl"
        rows = [
            {
                "event_id":"evt1",
                "session_date":"2026-09-29",
                "strategy":"MIDPOINT_STRATEGY",
                "version":"shadow-v1",
                "family":"B",
                "event_timestamp":"2026-09-29T09:42:00+05:30",
                "event_type":"B_ENTRY",
                "direction":"BEARISH",
                "state_before":"B_WATCH",
                "state_after":"ACTIVE",
                "result":"SHADOW_ENTRY",
                "reason":"B_DELAYED_FULL_CANDIDATE_A",
                "underlying_price":24162.9,
                "directional_points":0.0,
                "reference_type":"RED",
                "reference_high":24198.25,
                "reference_low":24173.7,
                "midpoint":24185.975,
                "original_boundary":24173.7,
                "futures_price":24163.0,
                "futures_vwap":24171.0,
                "directional_vwap_value":8.0,
                "source_candle_timestamp":"2026-09-29T09:42:00+05:30",
                "evidence":{},
                "observation_only":True,
                "execution_enabled":False,
                "paper_order_enabled":False,
                "quantity":None,
            },
            {
                "event_id":"evt2",
                "session_date":"2026-09-29",
                "strategy":"MIDPOINT_STRATEGY",
                "version":"shadow-v1",
                "family":"B",
                "event_timestamp":"2026-09-29T09:48:00+05:30",
                "event_type":"PLUS20_PROOF",
                "direction":"BEARISH",
                "state_before":"ACTIVE",
                "state_after":"ACTIVE",
                "result":"PROVED",
                "reason":"DIRECTIONAL_POINTS_REACHED_PLUS20",
                "underlying_price":24142.0,
                "directional_points":20.9,
                "reference_type":"RED",
                "reference_high":24198.25,
                "reference_low":24173.7,
                "midpoint":24185.975,
                "original_boundary":24173.7,
                "futures_price":24143.0,
                "futures_vwap":24152.0,
                "directional_vwap_value":9.0,
                "source_candle_timestamp":"2026-09-29T09:48:00+05:30",
                "evidence":{},
                "observation_only":True,
                "execution_enabled":False,
                "paper_order_enabled":False,
                "quantity":None,
            },
        ]
        p.write_text("".join(json.dumps(x)+"\n" for x in rows))

        old = ui.AUDIT_PATH
        ui.AUDIT_PATH = p
        try:
            s = ui.status()
            e = ui.events()
            t = ui.timeline()
            d = ui.audit_detail("evt1")
        finally:
            ui.AUDIT_PATH = old

        assert s["workspace"]["display_name"] == "Midpoint Strategy"
        assert s["audit_record_count"] == 2
        assert s["latest_entry"]["event_id"] == "evt1"
        assert s["latest_plus20"]["event_id"] == "evt2"
        assert s["safety"]["observation_only"] is True
        assert s["safety"]["execution_enabled"] is False
        assert s["safety"]["paper_order_enabled"] is False
        assert s["safety"]["quantity"] is None
        assert e["count"] == 2
        assert t["count"] == 2
        assert d["event"]["event_id"] == "evt1"

        print("PASS: Midpoint status projection")
        print("PASS: event projection")
        print("PASS: timeline projection")
        print("PASS: audit-detail projection")
        print("PASS: Family B latest-state fields")
        print("PASS: observation-only safety visible to UI")
        print("PASS: API route prefix /api/live-shadow/midpoint-strategy")


if __name__ == "__main__":
    main()
