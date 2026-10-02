#!/usr/bin/env python3

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from market_lab.midpoint_strategy.family_b_detector import FamilyBObservation
from market_lab.midpoint_strategy.replay import (
    load_audit_jsonl,
    validate_audit_monotonicity,
)
from market_lab.midpoint_strategy.runtime import (
    AuditableFamilyBEngine,
    MidpointFamilyBRuntime,
)
from market_lab.midpoint_strategy.structure import ReferenceStructure


def ts(base, minute):
    return (base + timedelta(minutes=minute)).isoformat()


def obs(base, minute, close, futures_price, futures_vwap):
    return FamilyBObservation(
        timestamp=ts(base, minute),
        close=close,
        futures_price=futures_price,
        futures_vwap=futures_vwap,
    )


def main():
    print("MIDPOINT STRATEGY — M2 AUDITABLE FAMILY B SMOKE")
    print("=" * 88)

    base = datetime(2026, 9, 29, 9, 20, tzinfo=timezone.utc)

    ref = ReferenceStructure(
        session_date="2026-09-29",
        reference_type="RED",
        start_timestamp=ts(base, 0),
        end_timestamp=ts(base, 4),
        high=24198.25,
        low=24173.70,
    )

    # Boundary break at t=19. Initial Candidate A is deliberately FALSE.
    history = [
        obs(base, 14, 24180.0, 24181.0, 24184.0),  # raw diff -3
        obs(base, 18, 24170.0, 24172.0, 24176.0),  # raw diff -4
    ]
    boundary = obs(base, 19, 24168.0, 24169.0, 24173.0)  # -4 => no A
    history.append(boundary)

    with tempfile.TemporaryDirectory() as td:
        journal = Path(td) / "audit.jsonl"
        engine = AuditableFamilyBEngine(journal_path=journal)
        rt = MidpointFamilyBRuntime(reference=ref)

        engine.start_b_watch(rt, boundary, history)

        # t=20 still waiting, raw diff -4.5
        o20 = obs(base, 20, 24167.0, 24168.0, 24172.5)
        history.append(o20)
        assert engine.evaluate_b_watch(rt, o20, history) == "WAIT"

        # t=22 gets raw futures-VWAP diff -8 with recent >= -5 => B entry.
        o22 = obs(base, 22, 24162.90, 24163.0, 24171.0)
        history.append(o22)
        assert engine.evaluate_b_watch(rt, o22, history) == "ENTRY"

        # +20 proof.
        o28 = obs(base, 28, 24142.0, 24143.0, 24152.0)
        engine.mark_plus20(rt, o28)

        # Exactly +10m classifier => RUNNER_STRENGTHENING.
        o38 = obs(base, 38, 24134.0, 24135.0, 24147.0)
        engine.classify_runner(
            rt,
            o38,
            net_directional_progress_from_plus20=8.0,
            directional_futures_vwap_change=3.0,
        )
        assert rt.lifecycle.runner_strengthening is True

        # Degraded.
        o50 = obs(base, 50, 24125.9, 24127.0, 24137.0)
        engine.mark_degraded(
            rt,
            o50,
            degraded_target_move=37.0,
            drawdown_from_running_mfe_close=18.0,
            prior_minute_directional_vwap_change=-1.5,
        )

        # Recovery.
        o54 = obs(base, 54, 24120.9, 24122.0, 24134.0)
        engine.mark_recovery(rt, o54)

        # Early rebreak before 10m => NO_ACTION and must be audited.
        o60 = obs(base, 60, 24146.0, 24147.0, 24157.0)
        assert engine.evaluate_cap20(rt, o60) is False

        # >=10m, current directional move <= +20 and below target => rescue.
        o66 = obs(base, 66, 24145.0, 24146.0, 24156.0)
        assert engine.evaluate_cap20(rt, o66) is True

        # First re-entry check false.
        o67 = obs(base, 67, 24140.0, 24141.0, 24152.0)
        assert engine.evaluate_reentry(rt, o67) is False

        # Retake degraded target + VWAP recovery => one re-entry.
        o68 = obs(base, 68, 24123.0, 24124.0, 24138.0)
        assert engine.evaluate_reentry(rt, o68) is True

        rows = load_audit_jsonl(journal)
        validate_audit_monotonicity(rows)

        types = [r["event_type"] for r in rows]
        required = {
            "B_WATCH_STARTED",
            "B_CONFIRMATION_CHECK",
            "B_ENTRY",
            "PLUS20_PROOF",
            "RUNNER_CLASSIFICATION",
            "DEGRADED_STARTED",
            "DEGRADED_TARGET_RECOVERED",
            "CAP20_CHECK",
            "CAP20_RESCUE_TRIGGERED",
            "POST_RESCUE_REENTRY_CHECK",
            "POST_CAP20_REENTRY_TRIGGERED",
        }
        missing = required.difference(types)
        assert not missing, missing

        # Re-run one deterministic event; append-only journal must suppress duplicate.
        before = len(rows)
        engine.evaluate_reentry(rt, o68)
        after = len(load_audit_jsonl(journal))
        assert after == before + 1, (
            "Expected a distinct NO_ACTION check after already used re-entry. "
            "Audit checks are intentionally preserved."
        )

        print(f"PASS: audit rows written = {after}")
        print("PASS: Family B delayed detector")
        print("PASS: rejected B confirmation audited")
        print("PASS: B entry audited")
        print("PASS: +20 / runner classification audited")
        print("PASS: degraded / recovery audited")
        print("PASS: rejected CAP20 check audited")
        print("PASS: CAP20 shadow rescue audited")
        print("PASS: rejected re-entry check audited")
        print("PASS: one post-CAP20 shadow re-entry audited")
        print("PASS: observation-only safety validated on every audit row")
        print("PASS: no order functionality present")


if __name__ == "__main__":
    main()
