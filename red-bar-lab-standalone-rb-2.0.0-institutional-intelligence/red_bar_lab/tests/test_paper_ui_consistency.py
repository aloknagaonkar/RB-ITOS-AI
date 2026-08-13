from pathlib import Path

from red_bar_lab.execution.trend_automation import EMA10TrendSnapshot
from red_bar_lab.ui.paper_consistency import (
    CandidateDetailDatabaseProxy,
    build_paper_exit_panel_wrapper,
)


class _FakeDatabase:
    def __init__(self, *, open_rows=None, queue_rows=None):
        self.open_rows = list(open_rows or [])
        self.queue_rows = list(queue_rows or [])

    def read_open_paper_execution_orders(self, account_id):
        return list(self.open_rows)

    def read_execution_queue(self, **kwargs):
        return list(self.queue_rows)

    def paper_execution_exists_for_signal(self, **kwargs):
        return True

    def read_signal_attempt_by_id(self, signal_id):
        return {
            "signal_id": signal_id,
            "direction": "BULLISH",
            "confirmation_high": 24500.0,
            "confirmation_low": 24400.0,
        }


def _contracts():
    return [
        {
            "tradingsymbol": "NIFTY24300CE",
            "instrument_token": 101,
        },
        {
            "tradingsymbol": "NIFTY24400CE",
            "instrument_token": 202,
        },
    ]


def test_candidate_detail_duplicate_is_scoped_to_selected_contract():
    database = _FakeDatabase(
        open_rows=[
            {
                "instrument_token": 101,
                "tradingsymbol": "NIFTY24300CE",
                "status": "OPEN",
            }
        ]
    )
    proxy = CandidateDetailDatabaseProxy(
        database,
        _contracts(),
        selected_symbol_provider=lambda: "NIFTY24400CE",
    )

    assert proxy.paper_execution_exists_for_signal(
        signal_id="S1",
        account_id="PAPER-STD",
    ) is False


def test_candidate_detail_open_selected_contract_is_duplicate():
    database = _FakeDatabase(
        open_rows=[
            {
                "instrument_token": 101,
                "tradingsymbol": "NIFTY24300CE",
                "status": "OPEN",
            }
        ]
    )
    proxy = CandidateDetailDatabaseProxy(
        database,
        _contracts(),
        selected_symbol_provider=lambda: "NIFTY24300CE",
    )

    assert proxy.paper_execution_exists_for_signal(
        signal_id="S1",
        account_id="PAPER-STD",
    ) is True


def test_candidate_detail_other_signal_pending_blocks_but_own_queue_does_not():
    database = _FakeDatabase(
        queue_rows=[
            {
                "signal_id": "S1",
                "instrument_token": 202,
                "candidate_symbol": "NIFTY24400CE",
                "status": "APPROVED",
            }
        ]
    )
    proxy = CandidateDetailDatabaseProxy(
        database,
        _contracts(),
        selected_symbol_provider=lambda: "NIFTY24400CE",
    )
    assert proxy.paper_execution_exists_for_signal(
        signal_id="S1",
        account_id="PAPER-STD",
    ) is False

    database.queue_rows.append(
        {
            "signal_id": "S2",
            "instrument_token": 202,
            "candidate_symbol": "NIFTY24400CE",
            "status": "QUALIFIED",
        }
    )
    assert proxy.paper_execution_exists_for_signal(
        signal_id="S1",
        account_id="PAPER-STD",
    ) is True


def test_exit_panel_wrapper_enriches_signal_with_completed_ema10():
    captured = {}

    def original(**kwargs):
        captured["signal"] = kwargs["database"].read_signal_attempt_by_id("S1")
        return "rendered"

    snapshot = EMA10TrendSnapshot(
        True,
        24525.0,
        24510.0,
        "2026-08-13T10:15:00+05:30",
        "READY",
    )
    wrapped = build_paper_exit_panel_wrapper(
        original,
        snapshot_loader=lambda market: snapshot,
    )

    result = wrapped(
        position={"order_id": "O1"},
        paper_engine=object(),
        paper_market=object(),
        database=_FakeDatabase(),
        intelligence_snapshot=None,
        instrument_key="NSE_INDEX|Nifty 50",
        today_text="2026-08-13",
    )

    assert result == "rendered"
    assert captured["signal"]["_ema10_5m_ready"] is True
    assert captured["signal"]["_ema10_5m_close"] == 24525.0
    assert captured["signal"]["_ema10_5m_value"] == 24510.0
    assert captured["signal"]["_ema10_5m_reason"] == "READY"


def test_workspace_wires_candidate_duplicate_and_exit_ema10_wrappers():
    root = Path(__file__).resolve().parents[1]
    source = (root / "ui" / "workspace.py").read_text(encoding="utf-8")

    assert "build_candidate_workbench_wrapper" in source
    assert "paper_trading._render_candidate_workbench_fragment" in source
    assert "build_paper_exit_panel_wrapper" in source
    assert "paper_trading._render_paper_exit_engine_panel" in source
