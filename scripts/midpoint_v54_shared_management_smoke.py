#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile

from market_lab.midpoint_strategy.config import MidpointShadowConfig
from market_lab.midpoint_strategy.family_b_detector import FamilyBObservation
from market_lab.midpoint_strategy.models import MidpointFamily
from market_lab.midpoint_strategy.runtime import AuditableFamilyBEngine, MidpointFamilyBRuntime
from market_lab.midpoint_strategy.structure import ReferenceStructure


def main():
    cfg = MidpointShadowConfig()
    cfg.assert_safe()

    assert cfg.family_b_enabled is True
    assert cfg.family_e_enabled is False
    assert cfg.observation_only is True
    assert cfg.execution_enabled is False
    assert cfg.paper_order_enabled is False
    assert cfg.quantity is None

    ref = ReferenceStructure(
        session_date="2026-09-28",
        reference_type="RED",
        start_timestamp="2026-09-28T09:20:00+05:30",
        end_timestamp="2026-09-28T09:24:00+05:30",
        high=22951.8,
        low=22914.1,
    )
    boundary = FamilyBObservation(
        timestamp="2026-09-28T09:26:00+05:30",
        close=22912.95,
        futures_price=22955.1,
        futures_vwap=22979.0055311973,
    )

    with tempfile.TemporaryDirectory() as td:
        engine = AuditableFamilyBEngine(
            journal_path=Path(td) / "audit.jsonl",
            config=cfg,
        )
        rt = MidpointFamilyBRuntime(reference=ref)
        engine.start_e_entry(rt, boundary)

        assert rt.family is MidpointFamily.E
        assert rt.lifecycle is not None
        assert rt.lifecycle.family is MidpointFamily.E

        plus20 = FamilyBObservation(
            timestamp="2026-09-28T09:35:00+05:30",
            close=22890.0,
            futures_price=22920.0,
            futures_vwap=22970.0,
        )
        engine.mark_plus20(rt, plus20)

        classifier = FamilyBObservation(
            timestamp="2026-09-28T09:45:00+05:30",
            close=22880.0,
            futures_price=22900.0,
            futures_vwap=22965.0,
        )
        engine.classify_runner(
            rt,
            classifier,
            net_directional_progress_from_plus20=10.0,
            directional_futures_vwap_change=15.0,
        )

        assert rt.lifecycle.runner_strengthening is True
        print("PASS V54 shared management smoke")
        print("family=E")
        print("same_manager=True")
        print("runner_strengthening=True")
        print("family_e_live_enabled=False")
        print("observation_only=True")
        print("execution_enabled=False")
        print("paper_order_enabled=False")
        print("quantity=None")

if __name__ == "__main__":
    main()
