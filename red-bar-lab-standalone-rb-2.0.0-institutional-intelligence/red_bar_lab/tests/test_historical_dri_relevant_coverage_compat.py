from types import SimpleNamespace

import pandas as pd

from red_bar_lab.services.historical_dri_relevant_coverage_compat import (
    analyze_historical_dri_relevant_coverage,
)


def test_global_ready_without_contract_rows_is_full_replay_ready():
    coverage = SimpleNamespace(
        replay_ready=True,
        fidelity="LIVE_CAPTURE_PARITY_HIGH",
        contracts=(),
    )
    underlying = pd.DataFrame(
        {
            "High": [24405.2],
            "Low": [24296.8],
            "Close": [24380.0],
        }
    )

    audit = analyze_historical_dri_relevant_coverage(coverage, underlying)

    assert audit.status == "FULL_REPLAY_READY"
    assert audit.global_replay_ready is True
    assert audit.reference_low == 24296.8
    assert audit.reference_high == 24405.2
