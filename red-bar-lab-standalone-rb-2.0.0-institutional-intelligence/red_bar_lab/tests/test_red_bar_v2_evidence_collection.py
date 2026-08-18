import sqlite3
from types import SimpleNamespace

from red_bar_lab.services.red_bar_v2_evidence_collection import (
    RedBarV2EvidenceStore,
    collect_promotion_evidence,
)


def _database(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE market_indicator_snapshots(snapshot_id TEXT PRIMARY KEY);
            CREATE TABLE red_bar_v2_direction_events(event_id TEXT PRIMARY KEY);
            CREATE TABLE candidate_admission_decisions(
                decision_id TEXT PRIMARY KEY,
                candidate_allowed INTEGER NOT NULL,
                duplicate_signal INTEGER NOT NULL,
                active_trade_count INTEGER NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO candidate_admission_decisions VALUES(?,?,?,?)",
            [
                ("A", 1, 0, 0),
                ("B", 0, 1, 1),
                ("C", 1, 1, 2),
            ],
        )
        conn.commit()


def test_collects_sqlite_and_jsonl_evidence(tmp_path):
    database_path = tmp_path / "red_bar.db"
    evidence_root = tmp_path / "runs"
    _database(database_path)
    store = RedBarV2EvidenceStore(evidence_root)

    store.record_replay(
        SimpleNamespace(
            trading_date="2026-08-21",
            instrument_key="NIFTY",
            admitted_candidates=2,
            blocked_candidates=3,
        )
    )
    store.record_parity(SimpleNamespace(matches=True, mismatch_fields=()))
    store.record_parity(SimpleNamespace(matches=False, mismatch_fields=("direction",)))
    store.record_shadow_session(
        session_id="S1",
        decisions=[SimpleNamespace(status="SHADOW_ADMITTED"), SimpleNamespace(status="BLOCKED")],
    )

    evidence = collect_promotion_evidence(
        database_path=database_path,
        evidence_root=evidence_root,
    )

    assert evidence.unit_tests_passed == 88
    assert evidence.replay_sessions == 1
    assert evidence.replay_candidates == 5
    assert evidence.replay_errors == 0
    assert evidence.parity_comparisons == 2
    assert evidence.parity_mismatches == 1
    assert evidence.shadow_sessions == 1
    assert evidence.shadow_decisions == 2
    assert evidence.shadow_errors == 0
    assert evidence.duplicate_entries == 1
    assert evidence.unresolved_lifecycle_conflicts == 1
    assert evidence.storage_audit_available is True


def test_invalid_jsonl_fails_closed_as_error(tmp_path):
    database_path = tmp_path / "red_bar.db"
    evidence_root = tmp_path / "runs"
    _database(database_path)
    evidence_root.mkdir(parents=True)
    (evidence_root / "replay_sessions.jsonl").write_text("not-json\n", encoding="utf-8")

    evidence = collect_promotion_evidence(
        database_path=database_path,
        evidence_root=evidence_root,
    )
    assert evidence.replay_sessions == 1
    assert evidence.replay_errors == 1


def test_missing_database_and_artifacts_remain_not_ready(tmp_path):
    evidence = collect_promotion_evidence(
        database_path=tmp_path / "missing.db",
        evidence_root=tmp_path / "missing-runs",
    )
    assert evidence.replay_sessions == 0
    assert evidence.parity_comparisons == 0
    assert evidence.shadow_sessions == 0
    assert evidence.storage_audit_available is False


def test_store_creates_append_only_files(tmp_path):
    store = RedBarV2EvidenceStore(tmp_path)
    result = SimpleNamespace(
        trading_date="2026-08-21",
        instrument_key="NIFTY",
        admitted_candidates=1,
        blocked_candidates=0,
    )
    store.record_replay(result)
    store.record_replay(result)
    lines = store.paths.replay.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
