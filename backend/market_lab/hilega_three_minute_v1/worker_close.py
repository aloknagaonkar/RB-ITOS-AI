"""Finalize the regular session even when the outer worker's in_session is false."""
from ..domain import IST

def process_after_close(now,selected,alignment_id,coordinator,process_tick):
    local=now.astimezone(IST)
    if (selected!=alignment_id or getattr(coordinator,'decision_interval_minutes',5)!=3
            or local.weekday()>=5 or local.strftime('%H:%M')<'15:30'
            or getattr(coordinator,'_cutoff_done_date',None)==local.date()):
        return False
    # The coordinator consumes only regular-session candles, blocks entries
    # at/after 15:30, and leaves missing close evidence pending. Revisit until
    # that day's exact final-minute evidence is available; never invent a fill.
    process_tick(now,[('hilega',coordinator.process)])
    return True
