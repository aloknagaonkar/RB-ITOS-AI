from datetime import date
from market_lab.midpoint_v2_break_and_go_archetype_study_v1 import (
    candidate_events, resolve_t3_timestamp, extract_economics_rows,
    parse_underlying_args, select_market
)

def test_candidate_selection_ignores_primary_outcome():
    state={"events":[
        {"block":"TRAIN","session_date":"2026-09-07","setup_type":"RED_BREAK","direction":"BEARISH","t3_state":"CONFIRM_CONTINUATION","primary_outcome":"RED_BEARISH_BASE_THEN_GO"},
        {"block":"TRAIN","session_date":"2026-09-03","setup_type":"RED_BREAK","direction":"BEARISH","t3_state":"CONFIRM_CONTINUATION","primary_outcome":"RED_BEARISH_BREAK_AND_GO"},
    ]}
    rows=candidate_events(state,date(2026,6,9),date(2026,9,7))
    assert [r["session_date"] for r in rows]==["2026-09-03","2026-09-07"]

def test_extract_nested_economics_row():
    doc={"x":[{"block":"TRAIN","session_date":"2026-09-07","setup_type":"RED_BREAK","direction":"BEARISH","t3_state":"CONFIRM_CONTINUATION","entry_timestamp":"2026-09-07T09:29:00+05:30","entry_price":74.75}]}
    assert len(extract_economics_rows(doc))==1

def test_resolve_t3_from_entry_minus_one():
    assert resolve_t3_timestamp({},{"entry_timestamp":"2026-09-07T09:29:00+05:30"})=="2026-09-07T09:28:00+05:30"

def test_block_aware_market_selection():
    markets={"TRAIN":{"a":1},"OOS_A":{"b":2}}
    m,src=select_market(markets,"OOS_A")
    assert src=="OOS_A" and m=={"b":2}

def test_wildcard_market_selection():
    markets={"*":{"x":1}}
    m,src=select_market(markets,"TRAIN")
    assert src=="*" and m=={"x":1}
