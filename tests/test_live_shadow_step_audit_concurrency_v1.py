from datetime import datetime, timedelta, timezone
from multiprocessing import get_context
from pathlib import Path

from market_lab.live_shadow_step_audit_v1 import (
    ShadowStepAuditStoreV1,
)


def _writer(
    path: str,
    worker_id: int,
    count: int,
    start_event,
) -> None:
    store = ShadowStepAuditStoreV1(Path(path))
    base = datetime(
        2026, 9, 25, 9, 15,
        tzinfo=timezone.utc,
    )

    # Release all processes together to exercise sequence allocation
    # against the same append-only audit file.
    start_event.wait()

    for i in range(count):
        store.append(
            event_time=base + timedelta(
                microseconds=(worker_id * count) + i
            ),
            checkpoint=base,
            stage="CONCURRENCY_TEST",
            status="PASS",
            payload={
                "worker_id": worker_id,
                "index": i,
            },
            observation_id=f"{worker_id}:{i}",
        )


def test_multiprocess_append_preserves_sequence_and_hash_chain(
    tmp_path,
):
    audit = tmp_path / "step-audit.jsonl"

    workers = 6
    per_worker = 25
    expected = workers * per_worker

    ctx = get_context("fork")
    start_event = ctx.Event()

    processes = [
        ctx.Process(
            target=_writer,
            args=(
                str(audit),
                worker_id,
                per_worker,
                start_event,
            ),
        )
        for worker_id in range(workers)
    ]

    for process in processes:
        process.start()

    start_event.set()

    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    store = ShadowStepAuditStoreV1(audit)
    rows = store.read_all()

    assert len(rows) == expected
    assert [row["sequence"] for row in rows] == list(
        range(1, expected + 1)
    )

    observation_ids = [
        row["observation_id"]
        for row in rows
    ]

    assert len(set(observation_ids)) == expected

    ok, issue = store.verify_chain()
    assert ok is True
    assert issue is None


def test_sequential_append_contract_remains_unchanged(
    tmp_path,
):
    audit = tmp_path / "step-audit.jsonl"
    store = ShadowStepAuditStoreV1(audit)

    first = store.append(
        event_time=datetime(
            2026, 9, 25, 9, 15,
            tzinfo=timezone.utc,
        ),
        checkpoint=None,
        stage="FIRST",
        status="PASS",
        payload={"x": 1},
        observation_id="first",
    )

    second = store.append(
        event_time=datetime(
            2026, 9, 25, 9, 16,
            tzinfo=timezone.utc,
        ),
        checkpoint=None,
        stage="SECOND",
        status="PASS",
        payload={"x": 2},
        observation_id="second",
    )

    assert first.sequence == 1
    assert first.previous_hash is None
    assert second.sequence == 2
    assert second.previous_hash == first.record_hash

    assert store.verify_chain() == (True, None)
