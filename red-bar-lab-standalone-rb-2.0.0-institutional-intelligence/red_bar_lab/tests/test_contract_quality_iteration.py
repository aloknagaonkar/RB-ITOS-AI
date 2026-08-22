import inspect

import pandas as pd

from red_bar_lab.intelligence.contract_quality import ContractQualityEngine


def test_contract_quality_avoids_iterrows_and_preserves_output():
    source = inspect.getsource(ContractQualityEngine)
    assert "iterrows(" not in source

    frame = pd.DataFrame(
        [
            {
                "strike": 25000,
                "call_ltp": 100,
                "put_ltp": 105,
                "call_oi": 600000,
                "put_oi": 550000,
                "call_volume": 1200000,
                "put_volume": 1100000,
            },
            {
                "strike": 25050,
                "call_ltp": 80,
                "put_ltp": 130,
                "call_oi": 300000,
                "put_oi": 350000,
                "call_volume": 500000,
                "put_volume": 600000,
            },
        ]
    )

    metrics = ContractQualityEngine.evaluate(frame)

    assert len(metrics) == 4
    assert {item.option_type for item in metrics} == {"CE", "PE"}
    assert all(0.0 <= item.quality_score <= 100.0 for item in metrics)
    assert ContractQualityEngine.infer_atm(frame) == 25000.0
