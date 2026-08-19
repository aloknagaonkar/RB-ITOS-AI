"""UI package initialization hooks."""

from red_bar_lab.ui import _shared
from red_bar_lab.ui.open_trade_row_enrichment import enrich_open_trade_rows


_original_arrow_safe_rows = _shared._arrow_safe_rows


def _arrow_safe_rows_with_open_trade_exit_progress(rows):
    return _original_arrow_safe_rows(enrich_open_trade_rows(rows))


# Paper Trading imports helpers using ``from red_bar_lab.ui._shared import *``.
# Install this narrowly scoped enrichment before page modules are imported so
# the existing Open Paper Position row gains exit progress without duplicating
# the table or changing paper-exit execution logic.
_shared._arrow_safe_rows = _arrow_safe_rows_with_open_trade_exit_progress
