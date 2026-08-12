import pandas as pd

from red_bar_lab.intelligence.contract_quality import ContractQualityEngine


def test_contract_quality_keeps_low_quality_contracts_visible_but_downweighted():
    frame = pd.DataFrame([
        {"strike": 24000, "call_ltp": 52, "put_ltp": 50, "call_oi": 1000000, "put_oi": 1000000, "call_volume": 1000000, "put_volume": 1000000},
        {"strike": 22000, "call_ltp": 2000, "put_ltp": 0.8, "call_oi": 500000, "put_oi": 10000, "call_volume": 200000, "put_volume": 5000},
    ])
    rows = {(r.strike, r.option_type): r for r in ContractQualityEngine.evaluate(frame)}

    assert rows[(24000.0, "PE")].quality_score > rows[(22000.0, "PE")].quality_score
    assert rows[(22000.0, "PE")].weight == 0.10
