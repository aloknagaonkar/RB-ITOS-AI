"""Tests for the V2 strategy PCR context panel on the Trade Evidence page.

Covers:
- _read_v2_pcr_evidence returns None when no audit row exists
- _read_v2_pcr_evidence returns the most recent row when multiple exist
- _format_v2_pcr_row returns UNAVAILABLE when no evidence
- _format_v2_pcr_row renders shift direction (bullish / bearish / stable)
- _format_v2_pcr_row handles missing shift gracefully
- _format_v2_pcr_row uses INFORMATIONAL status when evidence is present

Futures VWAP × PCR touch journal:
- _vwap_touch_events detects a touch only after price moved 10+ points away,
  and marks ACCEPTED/REJECTED from the next 15 closes
- _touch_day_pcr_rows returns chronological PCR rows with slope deltas
- _touch_pcr_context joins the nearest PCR row at/before the event within 600s
- _read_futures_touch_candles picks the longest candle list and degrades safely
- _futures_snapshot_days returns [] when the table is missing
- the summary cycle wires the touch journal panel

PCR Best-Trade Evaluation:
- _pcr_evaluation_band applies the trader's bands (≥1.25 / <0.7 / neutral)
- _pcr_evaluation_alignment maps band × side to ALIGNED/COUNTER/NEUTRAL
- _pcr_evaluation_trades normalizes recommendation rows into point outcomes
- _pcr_evaluation_alignment_summary aggregates hit rate and point averages
- _pcr_evaluation_vwap_events collects touch events across selected days
- the summary cycle wires the evaluation panel with the All-days replay
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fresh_db(tmp_path: Path) -> Path:
    """Create a fresh SQLite DB with the project schema."""
    from red_bar_lab.storage.database import RedBarDatabase

    db = tmp_path / "test.db"
    RedBarDatabase(db)
    return db


def _insert_evidence(
    db_path: Path,
    *,
    run_id: str,
    artifacts: dict[str, object],
    started_at: str = "2026-08-31T03:45:00+00:00",
) -> None:
    from red_bar_lab.storage.database import RedBarDatabase

    db = RedBarDatabase(db_path)
    db.write_step_evidence(
        process_name="red_bar_v2_strategy",
        run_id=run_id,
        step_name="check:pcr_informational",
        parent_step="strategy_evaluate",
        started_at=started_at,
        status="OK",
        artifacts=artifacts,
    )


def test_read_v2_pcr_evidence_returns_none_when_no_row(fresh_db: Path) -> None:
    from red_bar_lab.ui.market_direction_summary import _read_v2_pcr_evidence

    result = _read_v2_pcr_evidence(fresh_db)
    assert result is None


def test_read_v2_pcr_evidence_returns_latest_row(fresh_db: Path) -> None:
    from red_bar_lab.ui.market_direction_summary import _read_v2_pcr_evidence

    _insert_evidence(
        fresh_db,
        run_id="run-old",
        artifacts={"current_pcr": 0.90, "morning_pcr": 0.80, "shift": 0.10, "passed": True},
        started_at="2026-08-31T03:00:00+00:00",
    )
    _insert_evidence(
        fresh_db,
        run_id="run-new",
        artifacts={"current_pcr": 1.20, "morning_pcr": 0.95, "shift": 0.25, "passed": True},
        started_at="2026-08-31T04:00:00+00:00",
    )

    result = _read_v2_pcr_evidence(fresh_db)
    assert result is not None
    assert result["run_id"] == "run-new"
    assert result["step_name"] == "check:pcr_informational"
    assert result["artifacts"]["current_pcr"] == 1.20


def test_format_v2_pcr_row_unavailable_when_no_evidence() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    row = _format_v2_pcr_row(None)
    assert row["Status"] == "UNAVAILABLE"
    assert row["Live value"] == "Not available"
    assert "has not recorded" in row["Interpretation"]


def test_format_v2_pcr_row_renders_bullish_shift() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {
        "run_id": "run-1",
        "step_name": "check:pcr_informational",
        "status": "OK",
        "artifacts": {
            "current_pcr": 1.20,
            "morning_pcr": 0.95,
            "shift": 0.25,
            "passed": True,
        },
    }
    row = _format_v2_pcr_row(evidence)
    assert row["Status"] == "OK"
    assert row["Direction"] == "INFORMATIONAL"
    assert row["Live value"] == "1.200"
    assert "bullish" in row["Interpretation"]


def test_format_v2_pcr_row_renders_bearish_shift() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {
        "status": "OK",
        "artifacts": {
            "current_pcr": 0.70,
            "morning_pcr": 1.05,
            "shift": -0.35,
            "passed": True,
        },
    }
    row = _format_v2_pcr_row(evidence)
    assert "bearish" in row["Interpretation"]


def test_format_v2_pcr_row_renders_stable_shift() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {
        "status": "OK",
        "artifacts": {
            "current_pcr": 1.00,
            "morning_pcr": 1.01,
            "shift": -0.01,
            "passed": True,
        },
    }
    row = _format_v2_pcr_row(evidence)
    assert "stable" in row["Interpretation"]


def test_format_v2_pcr_row_handles_missing_shift() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {
        "status": "OK",
        "artifacts": {
            "current_pcr": 1.10,
            "morning_pcr": None,
            "shift": None,
            "passed": True,
        },
    }
    row = _format_v2_pcr_row(evidence)
    assert "not computable" in row["Interpretation"]


def test_format_v2_pcr_row_handles_only_current_pcr() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {
        "status": "OK",
        "artifacts": {
            "current_pcr": 1.10,
            "passed": True,
        },
    }
    row = _format_v2_pcr_row(evidence)
    assert "not computable" in row["Interpretation"]
    assert row["Live value"] == "1.100"


def test_format_v2_pcr_row_handles_empty_evidence_dict() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {"status": "OK", "artifacts": {}}
    row = _format_v2_pcr_row(evidence)
    assert row["Status"] == "UNAVAILABLE"


def test_format_v2_pcr_row_handles_non_dict_artifacts() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {"status": "OK", "artifacts": "garbage"}
    row = _format_v2_pcr_row(evidence)
    assert row["Status"] == "UNAVAILABLE"


def test_format_v2_pcr_row_status_propagates() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {
        "status": "ERROR",
        "artifacts": {
            "current_pcr": 1.10,
            "morning_pcr": 0.95,
            "shift": 0.15,
            "passed": True,
        },
    }
    row = _format_v2_pcr_row(evidence)
    assert row["Status"] == "ERROR"


def _create_journal_table(db_path: Path) -> None:
    import sqlite3

    connection = sqlite3.connect(db_path)
    connection.execute(
        """CREATE TABLE red_bar_v2_cycle_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            trading_date TEXT NOT NULL,
            admission_direction TEXT,
            admission_code TEXT,
            pcr_json TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    connection.commit()
    connection.close()


def _insert_journal_row(
    db_path: Path,
    *,
    run_id: str,
    observed_at: str,
    pcr_json: str,
    admission_direction: str | None = None,
    admission_code: str | None = None,
) -> None:
    import sqlite3

    connection = sqlite3.connect(db_path)
    connection.execute(
        """INSERT INTO red_bar_v2_cycle_evaluations
           (run_id, observed_at, trading_date, admission_direction,
            admission_code, pcr_json)
           VALUES (?,?,?,?,?,?)""",
        (
            run_id,
            observed_at,
            "2026-08-31",
            admission_direction,
            admission_code,
            pcr_json,
        ),
    )
    connection.commit()
    connection.close()


def test_read_v2_cycle_journal_pcr_none_without_table(fresh_db: Path) -> None:
    from red_bar_lab.ui.market_direction_summary import _read_v2_cycle_journal_pcr

    assert _read_v2_cycle_journal_pcr(fresh_db) is None


def test_read_v2_cycle_journal_pcr_skips_empty_and_returns_latest(
    fresh_db: Path,
) -> None:
    import json

    from red_bar_lab.ui.market_direction_summary import _read_v2_cycle_journal_pcr

    _create_journal_table(fresh_db)
    _insert_journal_row(
        fresh_db,
        run_id="run-old",
        observed_at="2026-08-31T10:00:00+05:30",
        pcr_json=json.dumps({"overall_pcr": 0.7, "overall_direction": "BEARISH"}),
    )
    _insert_journal_row(
        fresh_db,
        run_id="run-new",
        observed_at="2026-08-31T22:44:25+05:30",
        pcr_json=json.dumps(
            {
                "overall_pcr": 1.91,
                "overall_direction": "BULLISH",
                "morning_pcr": 1.30,
                "combined_pcr": 1.75,
            }
        ),
        admission_direction="BEARISH",
        admission_code="INITIAL_BEARISH_ALIGNMENT",
    )
    _insert_journal_row(
        fresh_db,
        run_id="run-newest-no-pcr",
        observed_at="2026-08-31T22:50:00+05:30",
        pcr_json="{}",
    )

    result = _read_v2_cycle_journal_pcr(fresh_db)
    assert result is not None
    assert result["run_id"] == "run-new"
    assert result["pcr"]["overall_pcr"] == 1.91
    assert result["pcr"]["morning_pcr"] == 1.30
    assert result["admission_direction"] == "BEARISH"
    assert result["admission_code"] == "INITIAL_BEARISH_ALIGNMENT"


def test_format_v2_journal_pcr_row_unavailable_and_observed() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_journal_pcr_row

    row = _format_v2_journal_pcr_row(None)
    assert row["Status"] == "UNAVAILABLE"
    assert row["Live value"] == "Not available"

    journal = {
        "pcr": {"overall_pcr": 1.916, "overall_direction": "BULLISH"},
        "observed_at": "2026-08-31T22:44:25+05:30",
    }
    row = _format_v2_journal_pcr_row(journal)
    assert row["Live value"] == "1.916"
    assert row["Direction"] == "BULLISH"
    assert row["Status"] == "OBSERVED"
    assert "observed at 2026-08-31T22:44:25+05:30" in row["Interpretation"]


def test_read_pcr_history_excludes_current_trading_day(tmp_path: Path) -> None:
    import sqlite3
    from datetime import datetime, timezone

    from red_bar_lab.ui.market_direction_summary import _read_pcr_history

    path = tmp_path / "research.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE market_trend_research_pcr_5m_history (
            underlying TEXT, trading_date TEXT, candle_close_timestamp TEXT,
            source_timestamp TEXT, overall_pcr REAL
        )"""
    )
    connection.executemany(
        "INSERT INTO market_trend_research_pcr_5m_history VALUES (?,?,?,?,?)",
        [
            (
                "NIFTY 50",
                "2026-08-28",
                "2026-08-28T09:55:00+00:00",
                "2026-08-28T10:00:00+00:00",
                1.20,
            ),
            (
                "NIFTY 50",
                "2026-08-31",
                "2026-08-31T08:00:00+00:00",
                "2026-08-31T08:05:00+00:00",
                2.00,
            ),
        ],
    )
    connection.commit()
    connection.close()

    now = datetime(2026, 8, 31, 6, 0, tzinfo=timezone.utc)
    history = _read_pcr_history(path, "NIFTY 50", now=now)
    assert history["previous_day_close"] == 1.20
    assert history["previous_day_date"] == "2026-08-28"
    assert history["rolling_mean"] == 1.20
    assert history["rolling_days_used"] == 1
    assert [pcr for _, pcr in history["sparkline"]] == [1.20, 2.00]


def test_summary_wires_history_helpers_and_journal_reader() -> None:
    import inspect

    from red_bar_lab.ui import market_direction_summary as summary

    source = inspect.getsource(summary)
    assert "_read_pcr_history(database_path, underlying)" in source
    assert "_format_history_rows(history)" in source
    assert "_render_history_sparkline(history)" in source
    assert "FRESHCROSS" not in source
    assert "red_bar_v2_cycle_evaluations" in source
    assert "_read_v2_cycle_journal_pcr(database_path)" in source


def _flat_candle(
    close: float,
    *,
    high: float | None = None,
    low: float | None = None,
    timestamp: str | None = None,
    volume: float = 1.0,
) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "close": close,
        "volume": volume,
    }


def _touch_candles(window_close: float) -> list[dict[str, object]]:
    """20 candles at 100, 5 at 115, one touch candle closing below VWAP,
    then 15 forward candles closing at ``window_close``."""
    candles = [_flat_candle(100.0) for _ in range(20)]
    candles.extend(_flat_candle(115.0) for _ in range(5))
    candles.append(
        _flat_candle(
            99.0,
            high=115.0,
            low=99.0,
            timestamp="2026-08-27 14:35:00+05:30",
        )
    )
    candles.extend(_flat_candle(window_close) for _ in range(15))
    return candles


def test_vwap_touch_events_detects_accepted_down_touch() -> None:
    from red_bar_lab.ui.market_direction_summary import (
        _vwap_series,
        _vwap_touch_events,
    )

    candles = _touch_candles(95.0)
    events = _vwap_touch_events(candles, _vwap_series(candles))
    assert len(events) == 1
    event = events[0]
    assert event["timestamp"] == "2026-08-27 14:35:00+05:30"
    assert event["approach"] == "DOWN"
    assert event["close_side"] == "BELOW"
    assert event["close"] == 99.0
    assert event["accepted"] is True
    assert event["next_move"] == pytest.approx(-4.0)


def test_vwap_touch_events_rejects_touch_when_window_fails_to_hold() -> None:
    from red_bar_lab.ui.market_direction_summary import (
        _vwap_series,
        _vwap_touch_events,
    )

    candles = _touch_candles(120.0)
    events = _vwap_touch_events(candles, _vwap_series(candles))
    assert len(events) == 1
    assert events[0]["approach"] == "DOWN"
    assert events[0]["accepted"] is False
    assert events[0]["next_move"] == pytest.approx(21.0)


def test_vwap_touch_events_ignores_moves_inside_threshold() -> None:
    from red_bar_lab.ui.market_direction_summary import (
        _vwap_series,
        _vwap_touch_events,
    )

    candles = [_flat_candle(100.0) for _ in range(30)]
    candles.append(_flat_candle(100.0, high=106.0, low=99.0))
    events = _vwap_touch_events(candles, _vwap_series(candles))
    assert events == []


class _FakePcrRepository:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.calls: list[dict[str, object]] = []

    def five_minute_pcr_history(
        self, *, underlying: str, trading_date: object, limit: int
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "underlying": underlying,
                "trading_date": trading_date,
                "limit": limit,
            }
        )
        return list(self._rows)


def test_touch_day_pcr_rows_orders_chronologically_and_computes_slope() -> None:
    from datetime import date

    from red_bar_lab.ui.market_direction_summary import _touch_day_pcr_rows

    repository = _FakePcrRepository(
        [
            {
                "candle_close_timestamp": "2026-08-27 14:35:00+05:30",
                "overall_pcr": 0.80,
                "research_direction": "WAIT",
            },
            {
                "candle_close_timestamp": "2026-08-27T14:30:00+05:30",
                "overall_pcr": 0.75,
                "research_direction": "WAIT",
            },
            {
                "candle_close_timestamp": "2026-08-27T14:25:00+05:30",
                "overall_pcr": None,
                "research_direction": None,
            },
        ]
    )
    rows = _touch_day_pcr_rows(
        repository, underlying="NIFTY 50", trading_day="2026-08-27"
    )
    assert repository.calls == [
        {
            "underlying": "NIFTY 50",
            "trading_date": date(2026, 8, 27),
            "limit": 100,
        }
    ]
    assert [row["overall"] for row in rows] == [0.75, 0.80]
    assert rows[0]["slope"] is None
    assert rows[1]["slope"] == pytest.approx(0.05)
    assert rows[1]["direction"] == "WAIT"
    assert rows[1]["ts"].isoformat() == "2026-08-27T14:35:00+05:30"


def test_touch_pcr_context_respects_event_bounds() -> None:
    from datetime import datetime, timedelta

    from red_bar_lab.ui.market_direction_summary import IST, _touch_pcr_context

    first = datetime(2026, 8, 27, 14, 30, tzinfo=IST)
    second = first + timedelta(minutes=5)
    rows = [
        {"ts": first, "overall": 0.75, "direction": "WAIT", "slope": None},
        {"ts": second, "overall": 0.80, "direction": "WAIT", "slope": 0.05},
    ]
    assert _touch_pcr_context(second, rows)["overall"] == 0.80
    assert _touch_pcr_context(first, rows)["overall"] == 0.75
    assert (
        _touch_pcr_context(second + timedelta(seconds=600), rows)["overall"]
        == 0.80
    )
    assert _touch_pcr_context(second + timedelta(seconds=601), rows) is None
    assert _touch_pcr_context(first - timedelta(seconds=1), rows) is None
    assert _touch_pcr_context(second, []) is None
    assert _touch_pcr_context(None, rows) is None


def _create_snapshot_table(db_path: Path) -> None:
    import sqlite3

    connection = sqlite3.connect(db_path)
    connection.execute(
        """CREATE TABLE nifty_futures_diagnostic_snapshots (
            observed_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )"""
    )
    connection.commit()
    connection.close()


def _insert_snapshot(
    db_path: Path, observed_at: str, payload: dict[str, object]
) -> None:
    import json
    import sqlite3

    connection = sqlite3.connect(db_path)
    connection.execute(
        "INSERT INTO nifty_futures_diagnostic_snapshots VALUES (?,?)",
        (observed_at, json.dumps(payload)),
    )
    connection.commit()
    connection.close()


def test_read_futures_touch_candles_prefers_longest_candle_list(
    tmp_path: Path,
) -> None:
    from red_bar_lab.ui.market_direction_summary import (
        _read_futures_touch_candles,
    )

    path = tmp_path / "futures.db"
    _create_snapshot_table(path)
    _insert_snapshot(
        path,
        "2026-08-27T13:00:00+05:30",
        {
            "market": {
                "completed_candles": [
                    {"close": 100.0},
                    {"close": 101.0},
                    {"close": 102.0},
                ],
                "futures_vwap": 101.5,
                "futures_vwap_acceptance": "BELOW_FALLING_VWAP",
                "futures_close_vs_vwap_points": -3.2,
            }
        },
    )
    _insert_snapshot(
        path,
        "2026-08-27T14:00:00+05:30",
        {
            "market": {
                "completed_candles": [{"close": 103.0}],
                "futures_vwap": 999.0,
            }
        },
    )
    _insert_snapshot(
        path,
        "2026-08-28T10:00:00+05:30",
        {"market": {"completed_candles": [{"close": 50.0}] * 9}},
    )

    candles, meta = _read_futures_touch_candles(path, "2026-08-27")
    assert [candle["close"] for candle in candles] == [100.0, 101.0, 102.0]
    assert meta["futures_vwap"] == 101.5
    assert meta["futures_vwap_acceptance"] == "BELOW_FALLING_VWAP"
    assert meta["futures_close_vs_vwap_points"] == pytest.approx(-3.2)

    assert _read_futures_touch_candles(path, "2026-08-29") == ([], {})


def test_futures_snapshot_days_handles_missing_table(tmp_path: Path) -> None:
    from red_bar_lab.ui.market_direction_summary import (
        _futures_snapshot_days,
        _read_futures_touch_candles,
    )

    missing = tmp_path / "missing.db"
    assert _futures_snapshot_days(missing) == []
    assert _read_futures_touch_candles(missing, "2026-08-27") == ([], {})

    path = tmp_path / "days.db"
    _create_snapshot_table(path)
    _insert_snapshot(path, "2026-08-27T13:00:00+05:30", {"market": {}})
    _insert_snapshot(path, "2026-08-28T13:00:00+05:30", {"market": {}})
    assert _futures_snapshot_days(path) == ["2026-08-28", "2026-08-27"]


def test_summary_wires_vwap_touch_journal_panel() -> None:
    import inspect

    from red_bar_lab.ui import market_direction_summary as summary

    source = inspect.getsource(summary)
    assert "_render_vwap_touch_journal(database_path)" in source
    assert '"vwap_touch_journal_trading_date"' in source
    assert "Futures VWAP × PCR touch journal" in source


def test_pcr_evaluation_band_boundaries() -> None:
    from red_bar_lab.ui.market_direction_summary import _pcr_evaluation_band

    assert _pcr_evaluation_band(1.50) == "BULLISH"
    assert _pcr_evaluation_band(1.25) == "BULLISH"
    assert _pcr_evaluation_band(1.24) == "NEUTRAL"
    assert _pcr_evaluation_band(0.70) == "NEUTRAL"
    assert _pcr_evaluation_band(0.69) == "BEARISH"
    assert _pcr_evaluation_band(None) == "UNAVAILABLE"


def test_pcr_evaluation_alignment_matrix() -> None:
    from red_bar_lab.ui.market_direction_summary import (
        _pcr_evaluation_alignment,
    )

    assert _pcr_evaluation_alignment("BULLISH", "CE") == "ALIGNED"
    assert _pcr_evaluation_alignment("BULLISH", "PE") == "COUNTER"
    assert _pcr_evaluation_alignment("BEARISH", "PE") == "ALIGNED"
    assert _pcr_evaluation_alignment("BEARISH", "CE") == "COUNTER"
    assert _pcr_evaluation_alignment("NEUTRAL", "CE") == "NEUTRAL"
    assert _pcr_evaluation_alignment("NEUTRAL", "PE") == "NEUTRAL"
    assert _pcr_evaluation_alignment("UNAVAILABLE", "CE") == "UNAVAILABLE"
    assert _pcr_evaluation_alignment("BULLISH", "") == "UNAVAILABLE"
    assert _pcr_evaluation_alignment("BEARISH", None) == "UNAVAILABLE"


def test_pcr_evaluation_trades_normalizes_rows() -> None:
    from red_bar_lab.ui.market_direction_summary import _pcr_evaluation_trades

    trades = _pcr_evaluation_trades(
        [
            {
                "opened_at": "2026-08-27T03:45:02+00:00",
                "symbol": "NIFTY 24350 PE 01 SEP 26 PE",
                "side": "PE",
                "strike": 24350,
                "entry_overall_pcr": 0.65,
                "entry_price": 120.0,
                "peak_price": 209.65,
                "current_price": 209.65,
                "status": "CLOSED",
            },
            {
                "opened_at": "2026-08-27T04:10:00+00:00",
                "symbol": None,
                "side": "CE",
                "strike": 25000,
                "entry_overall_pcr": 1.30,
                "entry_price": 100.0,
                "peak_price": None,
                "current_price": 90.0,
                "status": "ACTIVE",
            },
            "garbage",
        ]
    )
    assert len(trades) == 2
    first, second = trades
    assert first["contract"] == "NIFTY 24350 PE 01 SEP 26 PE"
    assert first["band"] == "BEARISH"
    assert first["alignment"] == "ALIGNED"
    assert first["peak_points"] == pytest.approx(89.65)
    assert first["last_points"] == pytest.approx(89.65)
    assert first["status"] == "CLOSED"
    assert second["contract"] == "25000 CE"
    assert second["band"] == "BULLISH"
    assert second["alignment"] == "ALIGNED"
    assert second["peak_points"] is None
    assert second["last_points"] == pytest.approx(-10.0)


def test_pcr_evaluation_alignment_summary_aggregates() -> None:
    from red_bar_lab.ui.market_direction_summary import (
        _pcr_evaluation_alignment_summary,
    )

    def trade(alignment: str, peak: float | None, last: float | None) -> dict:
        return {"alignment": alignment, "peak_points": peak, "last_points": last}

    summary = _pcr_evaluation_alignment_summary(
        [
            trade("ALIGNED", 20.0, 10.0),
            trade("ALIGNED", 30.0, 20.0),
            trade("COUNTER", -1.0, -60.0),
            trade("NEUTRAL", 15.0, -5.0),
            trade("UNAVAILABLE", 99.0, 99.0),
            trade("ALIGNED", None, None),
        ]
    )
    assert [row["Group"] for row in summary] == ["ALIGNED", "COUNTER", "NEUTRAL"]
    aligned, counter, neutral = summary
    assert aligned["Trades"] == 3
    assert aligned["Hit rate"] == "100%"
    assert aligned["Avg peak pts"] == "+25.0"
    assert aligned["Avg final pts"] == "+15.0"
    assert aligned["Best peak pts"] == "+30.0"
    assert counter["Trades"] == 1
    assert counter["Hit rate"] == "0%"
    assert counter["Avg final pts"] == "-60.0"
    assert neutral["Trades"] == 1
    assert neutral["Hit rate"] == "0%"


def test_pcr_evaluation_vwap_events_collects_across_days(tmp_path: Path) -> None:
    from red_bar_lab.ui.market_direction_summary import (
        _pcr_evaluation_vwap_events,
    )

    path = tmp_path / "evaluation.db"
    _create_snapshot_table(path)
    _insert_snapshot(
        path,
        "2026-08-27T15:00:00+05:30",
        {"market": {"completed_candles": _touch_candles(95.0)}},
    )
    events = _pcr_evaluation_vwap_events(path, ["2026-08-27", "2026-08-26"])
    assert len(events) == 1
    assert events[0]["accepted"] is True


def test_summary_wires_pcr_best_trade_evaluation_panel() -> None:
    import inspect

    from red_bar_lab.ui import market_direction_summary as summary

    source = inspect.getsource(summary)
    assert "_render_pcr_best_trade_evaluation(database_path, underlying)" in source
    assert '"pcr_best_trade_evaluation_trading_date"' in source
    assert "PCR Best-Trade Evaluation" in source
    assert "All days" in source
