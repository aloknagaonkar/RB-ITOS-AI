from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from time import monotonic

import pytest

from red_bar_lab.services.market_trend_research.models import DualPcrResearchSnapshot
from red_bar_lab.services.market_trend_research.repository import (
    MarketTrendResearchRepository,
    _utc_iso,
)
from red_bar_lab.tests.test_market_trend_research_repository_and_performance import _snapshot
from red_bar_lab.ui.market_trend_research_panel import (
    _current_rows,
    _source_age_seconds,
    _source_age_text,
)

IST = timezone(timedelta(hours=5, minutes=30))
OLDER_OFFSET = datetime(2026, 8, 24, 12, 28, 11, tzinfo=IST)
NEWER_UTC = datetime(2026, 8, 24, 6, 59, 56, tzinfo=timezone.utc)


def _snapshot_at(moment: datetime) -> DualPcrResearchSnapshot:
    base = _snapshot()
    panel = replace(base.current_panel, source_timestamp=moment)
    return replace(
        base,
        snapshot_id=DualPcrResearchSnapshot.build_id(
            underlying=base.underlying,
            provider=base.provider,
            source_timestamp=moment,
        ),
        source_timestamp=moment,
        evaluated_at=moment,
        current_panel=panel,
    )


def _seed_projection(path, *, snapshot_id: str, evaluated_at: str, source_timestamp: str, payload: dict[str, object]) -> None:
    repository = MarketTrendResearchRepository(path)
    with repository._connect() as connection:
        connection.execute(
            """INSERT INTO market_trend_research_snapshots
               (snapshot_id, underlying, trading_date, source_timestamp,
                evaluated_at, state, payload_json)
               VALUES (?,?,?,?,?,?,?)""",
            (
                snapshot_id,
                "NIFTY 50",
                "2026-08-24",
                source_timestamp,
                evaluated_at,
                "READY",
                json.dumps(payload),
            ),
        )
        connection.commit()


def test_latest_projection_orders_mixed_offsets_by_instant(tmp_path):
    path = tmp_path / "research.db"
    _seed_projection(
        path,
        snapshot_id="older",
        evaluated_at=OLDER_OFFSET.isoformat(),
        source_timestamp=OLDER_OFFSET.isoformat(),
        payload={"marker": "older"},
    )
    _seed_projection(
        path,
        snapshot_id="newer",
        evaluated_at=NEWER_UTC.isoformat(),
        source_timestamp=NEWER_UTC.isoformat(),
        payload={"marker": "newer"},
    )
    projection = MarketTrendResearchRepository(path).latest_projection(underlying="NIFTY 50")
    assert projection == {"marker": "newer"}


def test_retention_preserves_chronologically_newest_mixed_offsets(tmp_path):
    path = tmp_path / "research.db"
    repository = MarketTrendResearchRepository(path, retention=2)
    instants = (
        datetime(2026, 8, 24, 12, 28, 11, tzinfo=IST),
        datetime(2026, 8, 24, 6, 59, 56, tzinfo=timezone.utc),
        datetime(2026, 8, 24, 12, 31, 0, tzinfo=IST),
    )
    snapshots = [_snapshot_at(moment) for moment in instants]
    for snapshot in snapshots:
        repository.persist_once(
            snapshot,
            evaluation_started=monotonic(),
            database_read_ms=0.0,
            normalization_ms=0.0,
            calculation_ms=0.0,
            hard_deadline_ms=60_000.0,
        )
    with sqlite3.connect(path) as connection:
        retained = {
            row[0]
            for row in connection.execute(
                "SELECT snapshot_id FROM market_trend_research_snapshots"
            ).fetchall()
        }
    assert retained == {snapshots[1].snapshot_id, snapshots[2].snapshot_id}


def test_new_projection_ordering_columns_are_normalized_to_utc(tmp_path):
    path = tmp_path / "research.db"
    repository = MarketTrendResearchRepository(path)
    snapshot = _snapshot_at(OLDER_OFFSET)
    repository.persist(snapshot)
    with sqlite3.connect(path) as connection:
        source_timestamp, evaluated_at = connection.execute(
            """SELECT source_timestamp, evaluated_at
               FROM market_trend_research_snapshots WHERE snapshot_id=?""",
            (snapshot.snapshot_id,),
        ).fetchone()
    assert source_timestamp == "2026-08-24T06:58:11+00:00"
    assert evaluated_at == "2026-08-24T06:58:11+00:00"


def test_utc_normalization_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="source_timestamp must be timezone-aware"):
        _utc_iso(datetime(2026, 8, 24, 6, 58, 11), field_name="source_timestamp")


def test_live_source_age_uses_render_clock_not_persisted_age():
    source_timestamp = "2026-08-24T06:59:56+00:00"
    render_now = datetime(2026, 8, 24, 7, 9, 56, tzinfo=timezone.utc)
    live_age = _source_age_seconds(source_timestamp, now=render_now)
    assert live_age == 600.0
    assert _source_age_text(live_age) == "600.0 seconds"


@pytest.mark.parametrize("timestamp", ("not-a-timestamp", "2026-08-24T06:59:56", None, ""))
def test_malformed_or_naive_source_age_is_unavailable(timestamp):
    assert _source_age_seconds(
        timestamp,
        now=datetime(2026, 8, 24, 7, 9, 56, tzinfo=timezone.utc),
    ) is None
    assert _source_age_text(None) == "Not available"


def test_newest_projection_preserves_and_renders_10b1_day_fields(tmp_path):
    path = tmp_path / "research.db"
    day_row = {
        "strike": 24250.0,
        "position": "ATM",
        "ce_current_oi": 120.0,
        "ce_previous_day_oi": 90.0,
        "ce_previous_day_change": 30.0,
        "ce_previous_day_change_pct": 33.3333,
        "pe_current_oi": 150.0,
        "pe_previous_day_oi": 100.0,
        "pe_previous_day_change": 50.0,
        "pe_previous_day_change_pct": 50.0,
    }
    _seed_projection(
        path,
        snapshot_id="older",
        evaluated_at=OLDER_OFFSET.isoformat(),
        source_timestamp=OLDER_OFFSET.isoformat(),
        payload={"marker": "older", "current_panel": {"rows": []}},
    )
    _seed_projection(
        path,
        snapshot_id="newer",
        evaluated_at=NEWER_UTC.isoformat(),
        source_timestamp=NEWER_UTC.isoformat(),
        payload={"marker": "newer", "current_panel": {"rows": [day_row]}},
    )
    projection = MarketTrendResearchRepository(path).latest_projection(underlying="NIFTY 50")
    row = projection["current_panel"]["rows"][0]
    assert row["ce_previous_day_oi"] == 90.0
    assert row["ce_previous_day_change"] == 30.0
    assert row["ce_previous_day_change_pct"] == 33.3333
    assert row["pe_previous_day_oi"] == 100.0
    assert row["pe_previous_day_change"] == 50.0
    assert row["pe_previous_day_change_pct"] == 50.0

    rendered = _current_rows(projection["current_panel"])[0]
    assert rendered["CE previous-day OI"] == "90"
    assert rendered["CE OI change today"] == "+30"
    assert rendered["PE previous-day OI"] == "100"
    assert rendered["PE OI change today"] == "+50"


def test_ui_remains_projection_only_without_provider_or_per_row_queries():
    from pathlib import Path

    source = Path("red_bar_lab/ui/market_trend_research_panel.py").read_text(encoding="utf-8")
    assert "MarketTrendResearchRepository" in source
    assert "latest_projection" in source
    assert "Upstox" not in source
    assert "requests" not in source
    assert ".execute(" not in source
