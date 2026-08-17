from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st


@st.cache_data(ttl=300, show_spinner=False)
def _read_candle_csv(
    path_text: str,
    modified_ns: int,
    size_bytes: int,
) -> pd.DataFrame:
    """Read a candle artifact using file metadata as the cache identity.

    ``modified_ns`` and ``size_bytes`` are intentionally unused inside the
    function body. They are part of the Streamlit cache key so a replaced or
    appended candle artifact invalidates the cached frame immediately.
    """
    del modified_ns, size_bytes
    try:
        return pd.read_csv(path_text)
    except Exception:
        return pd.DataFrame()


def read_cached_strategy_candles(layout, instrument_key: str, trading_date: str):
    """Return the selected 1-minute candle artifact and a cached data frame.

    The function preserves the existing page-level reader signature, allowing
    it to be installed lazily without changing strategy-page behavior.
    """
    path = Path(layout.candle_path("upstox", instrument_key, 1, trading_date))
    if not path.exists():
        return path, pd.DataFrame()
    try:
        stat = path.stat()
    except OSError:
        return path, pd.DataFrame()
    frame = _read_candle_csv(
        str(path),
        int(stat.st_mtime_ns),
        int(stat.st_size),
    )
    return path, frame
