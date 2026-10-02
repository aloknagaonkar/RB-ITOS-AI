#!/usr/bin/env python3
from pathlib import Path

TARGET = Path("backend/market_lab/midpoint_strategy/live_shadow_v1.py")

def main():
    s = TARGET.read_text()
    original = s

    if "import json\n" not in s:
        marker = "from __future__ import annotations\n"
        if marker not in s:
            raise SystemExit("STOP: future import anchor missing")
        s = s.replace(marker, marker + "\nimport json\nimport os\n", 1)
    elif "import os\n" not in s:
        s = s.replace("import json\n", "import json\nimport os\n", 1)

    imp = "from .forward_oos_v62_1 import MidpointV621ForwardOOSCollector\n"
    if imp not in s:
        class_anchor = "class MidpointLiveShadowCoordinatorV1:"
        if class_anchor not in s:
            raise SystemExit("STOP: coordinator class anchor missing")
        s = s.replace(class_anchor, imp + "\n" + class_anchor, 1)

    init_anchor = '''        self.boundary_classifier = MidpointBoundaryClassifierV55()
        self.state: _SessionState | None = None
'''
    init_insert = '''        self.boundary_classifier = MidpointBoundaryClassifierV55()
        self.state: _SessionState | None = None

        # V62.2 forward-OOS research adapter. Disabled unless explicitly enabled.
        # It is observational only and never changes strategy decisions or orders.
        self._audit_path = Path(audit_path)
        self._v621_collector = None
        self._v621_audit_offset = 0
        if os.getenv("MIDPOINT_V62_OOS_COLLECTOR_ENABLED", "0") == "1":
            ledger_path = Path(
                os.getenv(
                    "MIDPOINT_V62_OOS_LEDGER",
                    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
                    "midpoint-v62-forward-reentry-oos/reentry-oos-ledger-v62.csv",
                )
            )
            self._v621_collector = MidpointV621ForwardOOSCollector(ledger_path)
            if self._audit_path.exists():
                self._v621_audit_offset = self._audit_path.stat().st_size
'''
    if "_v621_collector" not in s:
        if init_anchor not in s:
            raise SystemExit("STOP: __init__ anchor missing")
        s = s.replace(init_anchor, init_insert, 1)

    helper_anchor = "    def _process_minute(\n"
    helper = '''    def _v621_read_new_audit_events(self) -> list[dict]:
        if self._v621_collector is None or not self._audit_path.exists():
            return []

        events: list[dict] = []
        with self._audit_path.open("rb") as fh:
            fh.seek(self._v621_audit_offset)
            payload = fh.read()
            self._v621_audit_offset = fh.tell()

        for raw in payload.splitlines():
            if not raw.strip():
                continue
            try:
                events.append(json.loads(raw.decode("utf-8")))
            except Exception:
                # Research sidecar must never interrupt live-shadow processing.
                continue
        return events

    def _v621_observe_completed_minute(self, *, ts: datetime, underlying) -> None:
        if self._v621_collector is None:
            return

        events = self._v621_read_new_audit_events()

        # Feed non-terminal audit events first so a newly-created re-entry exists
        # before future candles are evaluated. Then feed this completed candle.
        # Feed STRUCTURAL_TERMINAL last so R1/R2 can still react to the terminal
        # candle's completed OHLC before the research case is finalized.
        terminal_events = []
        for event in events:
            if event.get("event_type") == "STRUCTURAL_TERMINAL":
                terminal_events.append(event)
            else:
                self._v621_collector.on_audit_event(event)

        self._v621_collector.on_completed_underlying_candle(
            timestamp=ts.isoformat(),
            high=self._float(underlying, "high"),
            low=self._float(underlying, "low"),
            close=self._float(underlying, "close"),
        )

        for event in terminal_events:
            self._v621_collector.on_audit_event(event)

'''
    if "def _v621_observe_completed_minute" not in s:
        if helper_anchor not in s:
            raise SystemExit("STOP: _process_minute anchor missing")
        s = s.replace(helper_anchor, helper + helper_anchor, 1)

    call_anchor = '''            self._process_minute(
                ts=ts,
                underlying=underlying_by_ts[ts],
                futures_close=f_close,
                futures_vwap=f_vwap,
                underlying_by_ts=underlying_by_ts,
            )
            self.state.processed_minutes.add(ts)
'''
    call_insert = '''            self._process_minute(
                ts=ts,
                underlying=underlying_by_ts[ts],
                futures_close=f_close,
                futures_vwap=f_vwap,
                underlying_by_ts=underlying_by_ts,
            )
            self._v621_observe_completed_minute(
                ts=ts,
                underlying=underlying_by_ts[ts],
            )
            self.state.processed_minutes.add(ts)
'''
    process_tail = s.split("def process(",1)[-1] if "def process(" in s else ""
    if "self._v621_observe_completed_minute(" not in process_tail:
        if call_anchor not in s:
            raise SystemExit("STOP: process() call anchor missing")
        s = s.replace(call_anchor, call_insert, 1)

    backup = TARGET.with_suffix(TARGET.suffix + ".pre-v62-2.bak")
    if s != original:
        if not backup.exists():
            backup.write_text(original)
        TARGET.write_text(s)

    print(f"Patched: {TARGET}")
    print("PASS: V62.2 adapter installed behind MIDPOINT_V62_OOS_COLLECTOR_ENABLED=1")
    print("Default remains disabled.")
    print("No B/E/CAP20/re-entry/order logic changed.")

if __name__ == "__main__":
    main()
