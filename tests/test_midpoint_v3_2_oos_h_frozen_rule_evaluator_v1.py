from types import SimpleNamespace

from market_lab.midpoint_v3_2_oos_h_frozen_rule_evaluator_v1 import (
    build_holdout_checkpoint_rows,
    build_holdout_events,
)


class FakeStrength:
    CHECKPOINTS = (0, 1, 3)

    @staticmethod
    def direction_for_event(event):
        return event["direction"]

    @staticmethod
    def snapshot_at(event, cp):
        return event["snapshots"].get(cp)

    @staticmethod
    def oi_state(snapshot, side):
        return snapshot[f"{side.lower()}_state"]

    @staticmethod
    def classify_oi_pair(direction, ce, pe):
        return {"quality": "STRONG"}

    @staticmethod
    def first_num(snapshot, names):
        for name in names:
            if name in snapshot:
                return snapshot[name]
        return None

    @staticmethod
    def extract_features(snapshot, direction):
        return dict(snapshot["features"])


def test_holdout_checkpoint_rows_ignore_future_outcome():
    framework = {
        "events": [
            {
                "block": "OOS_H",
                "session_date": "2025-12-12",
                "setup_type": "RED",
                "direction": "BEARISH",
                "primary_outcome": "SOME_FUTURE_LABEL",
                "snapshots": {
                    1: {
                        "timestamp": "2025-12-12T10:00:00+05:30",
                        "ce_state": "SHORT_BUILDUP",
                        "pe_state": "LONG_BUILDUP",
                        "features": {"progress_points": 2.0},
                    },
                    3: {
                        "timestamp": "2025-12-12T10:02:00+05:30",
                        "ce_state": "SHORT_BUILDUP",
                        "pe_state": "LONG_BUILDUP",
                        "features": {"progress_points": 5.0},
                    },
                },
            }
        ]
    }

    rows = build_holdout_checkpoint_rows(
        framework, strength_module=FakeStrength
    )

    assert len(rows) == 2
    assert all(row["primary_outcome"] is None for row in rows)
    assert all(row["outcome_label"] is None for row in rows)
    assert {row["checkpoint_minutes"] for row in rows} == {1, 3}


class FakeDiagnostics:
    @staticmethod
    def event_key(row):
        return (
            row["block"],
            row["session_date"],
            row["setup_type"],
            row["direction"],
        )


class FakeState:
    @staticmethod
    def observe_t1(row):
        return {"state": "OBSERVE_STRONG"}

    @staticmethod
    def score_t3(row, rules):
        return {"oi_quality": "STRONG", "passes": 5}

    @staticmethod
    def classify_t3(row, scored):
        return "CONFIRM_CONTINUATION"


def test_build_holdout_events_does_not_require_outcome_label():
    rows = [
        {
            "block": "OOS_H",
            "session_date": "2025-12-12",
            "setup_type": "RED",
            "direction": "BEARISH",
            "primary_outcome": None,
            "outcome_label": None,
            "checkpoint_minutes": 1,
            "timestamp": "2025-12-12T10:00:00+05:30",
        },
        {
            "block": "OOS_H",
            "session_date": "2025-12-12",
            "setup_type": "RED",
            "direction": "BEARISH",
            "primary_outcome": None,
            "outcome_label": None,
            "checkpoint_minutes": 3,
            "timestamp": "2025-12-12T10:02:00+05:30",
            "exact_oi_transition_t1_to_t3": "STABLE",
        },
    ]

    events = build_holdout_events(
        rows,
        {"BEARISH": {"features": {}}},
        diagnostics_module=FakeDiagnostics,
        state_module=FakeState,
    )

    assert len(events) == 1
    event = events[0]
    assert event["t3_state"] == "CONFIRM_CONTINUATION"
    assert event["primary_outcome"] is None
    assert event["outcome_label"] is None
    assert event["t3_timestamp"] == "2025-12-12T10:02:00+05:30"


def test_non_h_events_are_ignored():
    framework = {
        "events": [
            {
                "block": "OOS_G",
                "session_date": "2026-01-12",
                "setup_type": "RED",
                "direction": "BEARISH",
                "snapshots": {},
            }
        ]
    }

    rows = build_holdout_checkpoint_rows(
        framework, strength_module=FakeStrength
    )
    assert rows == []
