import sqlite3
from pathlib import Path

from red_bar_lab.services.market_evidence_bundle_store import (
    SCHEMA_VERSION,
    persist_market_evidence_bundle,
    read_latest_market_evidence_bundle,
)


def test_incompatible_legacy_table_is_not_read_or_mutated(tmp_path: Path):
    database_path = tmp_path / "evidence.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE market_evidence_bundles (bundle_id TEXT PRIMARY KEY)"
        )
        before = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='market_evidence_bundles'"
        ).fetchone()[0]

    assert read_latest_market_evidence_bundle(
        database_path,
        underlying_name="NIFTY 50",
    ) is None

    with sqlite3.connect(database_path) as connection:
        after = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='market_evidence_bundles'"
        ).fetchone()[0]
    assert after == before


def test_compatible_bundle_reports_schema_version(tmp_path: Path):
    database_path = tmp_path / "evidence.sqlite"
    persist_market_evidence_bundle(
        database_path,
        underlying_name="NIFTY 50",
        view={
            "as_of_timestamp": "2026-08-22T09:21:00+00:00",
            "underlying_bar_close_timestamp": "2026-08-22T09:20:00+00:00",
            "futures_bar_close_timestamp": "2026-08-22T09:20:00+00:00",
            "option_timestamp": "2026-08-22T09:20:30+00:00",
            "blocking_reasons": [],
            "caution_reasons": [],
        },
    )

    bundle = read_latest_market_evidence_bundle(
        database_path,
        underlying_name="NIFTY 50",
    )

    assert bundle is not None
    assert bundle["schema_version"] == SCHEMA_VERSION
