from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st


def _arrow_safe_value(value):
    """Normalize UI values so Streamlit/PyArrow sees stable column types."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value, (list, tuple, dict, set)):
        return str(value)
    return str(value)


def _arrow_safe_rows(rows):
    """Return row mappings with Arrow-safe scalar values."""
    if rows is None:
        return []
    safe = []
    for row in rows:
        if hasattr(row, "items"):
            safe.append(
                {
                    str(key): _arrow_safe_value(value)
                    for key, value in row.items()
                }
            )
        else:
            safe.append({"value": _arrow_safe_value(row)})
    return safe


__all__ = ["date", "pd", "st", "_arrow_safe_rows"]
