from datetime import datetime
from market_lab.midpoint_oi_vwap_controlled_comparison_v1 import confluence_direction,floor_completed_5m

def test_floor_does_not_look_forward(): assert floor_completed_5m(datetime(2026,9,15,9,28))==datetime(2026,9,15,9,25)
def test_exact_checkpoint_unchanged(): assert floor_completed_5m(datetime(2026,9,15,9,30))==datetime(2026,9,15,9,30)
def test_bullish_confluence(): assert confluence_direction({"ce_state":"LONG_BUILDUP","pe_state":"SHORT_BUILDUP","futures_close":101,"futures_vwap":100})=="BULLISH"
def test_bearish_confluence(): assert confluence_direction({"ce_state":"SHORT_BUILDUP","pe_state":"LONG_BUILDUP","futures_close":99,"futures_vwap":100})=="BEARISH"
def test_misaligned_is_neutral(): assert confluence_direction({"ce_state":"LONG_BUILDUP","pe_state":"SHORT_BUILDUP","futures_close":99,"futures_vwap":100})=="NEUTRAL"

def test_comparison_reads_canonical_session_vwap(tmp_path):
    from market_lab.midpoint_oi_vwap_controlled_comparison_v1 import load_futures

    p = tmp_path / "futures.csv"
    p.write_text(
        "session_date,timestamp,close,session_vwap,instrument_key,expiry\n"
        "2026-09-15,2026-09-15T09:25:00+05:30,24990,25000,NSE_FO|TEST,2026-09-29\n"
    )

    idx = load_futures(p)
    row = idx[("2026-09-15", "2026-09-15T09:25:00+05:30")]

    assert row["futures_close"] == 24990
    assert row["futures_vwap"] == 25000

def test_positioning_separates_5m_filter_from_exact_atm_contract(tmp_path):
    from pathlib import Path
    from market_lab.midpoint_oi_vwap_controlled_comparison_v1 import (
        load_positioning,
    )

    p = tmp_path / "positioning.csv"

    p.write_text(
        "session_date,timestamp,strike_offset,moving_atm,"
        "ce_5m_state,pe_5m_state,"
        "ce_instrument_key,pe_instrument_key\n"

        "2026-09-15,2026-09-15T09:25:00+05:30,0,25000,"
        "SHORT_BUILDUP,LONG_BUILDUP,"
        "CE_0925,PE_0925\n"

        "2026-09-15,2026-09-15T09:28:00+05:30,0,24950,"
        "SHORT_BUILDUP,LONG_BUILDUP,"
        "CE_0928,PE_0928\n"
    )

    checkpoint, exact = load_positioning(
        [("TRAIN", Path(p))]
    )

    cp = checkpoint[
        (
            "TRAIN",
            "2026-09-15",
            "2026-09-15T09:25:00+05:30",
        )
    ]

    atm = exact[
        (
            "TRAIN",
            "2026-09-15",
            "2026-09-15T09:28:00+05:30",
        )
    ]

    assert cp["ce_state"] == "SHORT_BUILDUP"
    assert cp["pe_state"] == "LONG_BUILDUP"

    assert atm["moving_atm"] == 24950
    assert atm["pe_instrument_key"] == "PE_0928"


def test_non_5m_row_not_used_as_oi_checkpoint(tmp_path):
    from pathlib import Path
    from market_lab.midpoint_oi_vwap_controlled_comparison_v1 import (
        load_positioning,
    )

    p = tmp_path / "positioning.csv"

    p.write_text(
        "session_date,timestamp,strike_offset,moving_atm,"
        "ce_5m_state,pe_5m_state,"
        "ce_instrument_key,pe_instrument_key\n"
        "2026-09-15,2026-09-15T09:28:00+05:30,0,24950,"
        "SHORT_BUILDUP,LONG_BUILDUP,"
        "CE_0928,PE_0928\n"
    )

    checkpoint, exact = load_positioning(
        [("TRAIN", Path(p))]
    )

    assert (
        "TRAIN",
        "2026-09-15",
        "2026-09-15T09:28:00+05:30",
    ) not in checkpoint

    assert (
        "TRAIN",
        "2026-09-15",
        "2026-09-15T09:28:00+05:30",
    ) in exact
