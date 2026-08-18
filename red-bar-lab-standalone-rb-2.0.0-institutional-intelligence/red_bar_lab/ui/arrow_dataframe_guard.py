from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pandas as pd


_GUARD_MARKER = "_rb_arrow_dataframe_guard_installed"


def _display_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (Mapping, list, tuple, set)):
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def arrow_safe_frame(data: object) -> object:
    """Normalize only mixed/nested display columns before Arrow serialization."""
    if isinstance(data, pd.io.formats.style.Styler):
        return data
    if isinstance(data, pd.DataFrame):
        frame = data.copy()
    elif isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
        try:
            frame = pd.DataFrame(data)
        except Exception:
            return data
    elif isinstance(data, Mapping):
        try:
            frame = pd.DataFrame(data)
        except Exception:
            return data
    else:
        return data

    for column in frame.columns:
        series = frame[column]
        non_null = [value for value in series.tolist() if value is not None and not pd.isna(value)]
        if not non_null:
            continue
        has_nested = any(isinstance(value, (Mapping, list, tuple, set)) for value in non_null)
        type_families = {
            "bool" if isinstance(value, bool)
            else "number" if isinstance(value, (int, float)) and not isinstance(value, bool)
            else "text" if isinstance(value, (str, bytes))
            else type(value).__name__
            for value in non_null
        }
        if has_nested or len(type_families) > 1:
            frame[column] = series.map(_display_text)
    return frame


def install(streamlit_module) -> None:
    """Install one idempotent dataframe guard on the shared Streamlit module."""
    if getattr(streamlit_module, _GUARD_MARKER, False):
        return
    original = streamlit_module.dataframe

    def guarded_dataframe(data=None, *args, **kwargs):
        return original(arrow_safe_frame(data), *args, **kwargs)

    streamlit_module.dataframe = guarded_dataframe
    setattr(streamlit_module, _GUARD_MARKER, True)


__all__ = ["arrow_safe_frame", "install"]
