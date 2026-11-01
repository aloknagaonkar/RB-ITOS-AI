"""Presentation only: resolve audited owner or pending direction, never recalculate signals."""
def resolve_audit_direction(row):
    after=str(row.get('owner_after') or row.get('trade_owner_after') or '').upper()
    if after in ('BULLISH','BEARISH'):return after
    events=row.get('accepted_events') or []
    if isinstance(events,str):events=events.split(',')
    if any('EXIT' in str(event) for event in events):
        before=str(row.get('owner_before') or row.get('trade_owner_before') or '').upper()
        if before in ('BULLISH','BEARISH'):return before
    bullish=row.get('bullish_armed') is True;bearish=row.get('bearish_armed') is True
    if bearish and not bullish:return 'BEARISH'
    if bullish and not bearish:return 'BULLISH'
    checks=row.get('wma_gap_checks') or row.get('checks') or []
    directions={str(c.get('direction') or '').upper() for c in checks if c.get('direction') in ('BULLISH','BEARISH')}
    if len(directions)==1:return next(iter(directions))
    if 'ARMED' in str(row.get('bearish_state') or '') and 'ARMED' not in str(row.get('bullish_state') or ''):return 'BEARISH'
    if 'ARMED' in str(row.get('bullish_state') or '') and 'ARMED' not in str(row.get('bearish_state') or ''):return 'BULLISH'
    for event in events:
        event=str(event)
        if event.startswith('ENTRY_'):return 'BEARISH' if 'BEARISH' in event else 'BULLISH'
    return None
