from __future__ import annotations

import pandas as pd
import pyarrow as pa

from red_bar_lab.ui._shared import _arrow_safe_dataframe


def test_mixed_actual_column_is_arrow_serializable():
    rows = [
        {"check": "coverage", "actual": 88.5},
        {"check": "source", "actual": "LIVE_MARKET_CAPTURE"},
        {"check": "missing", "actual": None},
        {"check": "flags", "actual": ["bid", "ask"]},
        {"check": "raw", "actual": b"AVAILABLE"},
    ]

    safe = _arrow_safe_dataframe(rows)
    table = pa.Table.from_pandas(safe, preserve_index=False)

    assert table.num_rows == 5
    assert safe["actual"].dropna().map(type).eq(str).all()
    assert safe.loc[0, "actual"] == "88.5"
    assert safe.loc[1, "actual"] == "LIVE_MARKET_CAPTURE"
    assert safe.loc[4, "actual"] == "AVAILABLE"


def test_numeric_columns_remain_numeric():
    safe = _arrow_safe_dataframe([
        {"score": 80.0, "count": 2},
        {"score": 72.5, "count": 3},
    ])

    assert pd.api.types.is_float_dtype(safe["score"])
    assert pd.api.types.is_integer_dtype(safe["count"])
    pa.Table.from_pandas(safe, preserve_index=False)
