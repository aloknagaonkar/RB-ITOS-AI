from __future__ import annotations

import pandas as pd

from red_bar_lab.ui.arrow_dataframe_guard import arrow_safe_frame, install


def test_mixed_raw_value_column_becomes_text():
    frame = arrow_safe_frame([
        {"component": "score", "raw_value": 90.0},
        {"component": "metadata", "raw_value": "MISSING_INSTRUMENT_TOKEN"},
    ])
    assert isinstance(frame, pd.DataFrame)
    assert frame["raw_value"].tolist() == ["90.0", "MISSING_INSTRUMENT_TOKEN"]


def test_mixed_detail_column_becomes_text():
    frame = arrow_safe_frame([
        {"check": "A", "detail": "OK"},
        {"check": "B", "detail": 12.5},
    ])
    assert frame["detail"].tolist() == ["OK", "12.5"]


def test_nested_values_are_json_text():
    frame = arrow_safe_frame([
        {"field": "positions", "value": []},
        {"field": "risk", "value": {"used": 10.0}},
    ])
    assert frame["value"].tolist() == ["[]", '{"used": 10.0}']


def test_homogeneous_numeric_column_is_preserved():
    frame = arrow_safe_frame([{"value": 1.0}, {"value": 2.0}])
    assert frame["value"].tolist() == [1.0, 2.0]


def test_install_is_idempotent_and_sanitizes_before_render():
    captured = []

    class FakeStreamlit:
        def dataframe(self, data=None, *args, **kwargs):
            captured.append(data)
            return "rendered"

    fake = FakeStreamlit()
    install(fake)
    guarded = fake.dataframe
    install(fake)
    assert fake.dataframe is guarded
    assert fake.dataframe([{"detail": "OK"}, {"detail": 1.0}]) == "rendered"
    assert captured[0]["detail"].tolist() == ["OK", "1.0"]
