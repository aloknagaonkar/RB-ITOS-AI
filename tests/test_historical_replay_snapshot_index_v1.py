from datetime import datetime, timedelta, timezone

from market_lab.historical_replay_snapshot_index_v1 import (
    HistoricalReplaySnapshotIndexV1,
    IndexedRawSnapshot,
)


def test_index_selects_first_at_or_after_and_enforces_30_seconds():
    base = datetime(2026, 9, 18, 3, 50, tzinfo=timezone.utc)
    parsed = []

    def parse(raw):
        parsed.append(raw["id"])
        return raw["id"]

    idx = HistoricalReplaySnapshotIndexV1(
        [
            IndexedRawSnapshot(base + timedelta(seconds=4), {"id": "a"}),
            IndexedRawSnapshot(base + timedelta(seconds=21), {"id": "b"}),
            IndexedRawSnapshot(base + timedelta(seconds=45), {"id": "c"}),
        ],
        parse_fn=parse,
    )

    assert idx.select_first_at_or_after(base) == "a"
    assert idx.select_first_at_or_after(base + timedelta(seconds=5)) == "b"
    assert idx.select_first_at_or_after(base + timedelta(seconds=22)) == "c"
    assert idx.select_first_at_or_after(base + timedelta(minutes=1)) is None


def test_selected_snapshot_is_parsed_once():
    base = datetime(2026, 9, 18, 3, 50, tzinfo=timezone.utc)
    calls = []

    def parse(raw):
        calls.append(raw["id"])
        return raw

    idx = HistoricalReplaySnapshotIndexV1(
        [IndexedRawSnapshot(base + timedelta(seconds=3), {"id": "x"})],
        parse_fn=parse,
    )

    assert idx.select_first_at_or_after(base)["id"] == "x"
    assert idx.select_first_at_or_after(base)["id"] == "x"
    assert calls == ["x"]
    assert idx.parsed_count == 1
