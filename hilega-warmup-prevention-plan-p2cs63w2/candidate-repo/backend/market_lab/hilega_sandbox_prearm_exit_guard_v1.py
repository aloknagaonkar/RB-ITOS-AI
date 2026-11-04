"""Skip only provable pre-arm exits with no Sandbox submission history."""
def is_prearm_exit(intent, intents, control, dispatch_rows):
    if intent.get('event_type') != 'EXIT' or not intent.get('trade_id'):
        return False
    baseline=int(control.get('baseline_source_sequence') or 0)
    entries=[r for r in intents if r.get('event_type')=='ENTRY'
        and r.get('decision')=='WOULD_SUBMIT' and r.get('trade_id')==intent['trade_id']]
    if len(entries)!=1:
        return False
    entry=entries[0]
    sequence=int(entry.get('source_sequence') or 0)
    same_day=str(entry.get('event_timestamp',''))[:10]==str(control.get('session_date'))==str(intent.get('event_timestamp',''))[:10]
    same_direction=entry.get('direction')==intent.get('direction') and entry.get('direction') in ('BULLISH','BEARISH')
    # Any attempted dispatch makes this a reconciliation issue, not a harmless skip.
    submitted=any(r.get('trade_id')==intent['trade_id'] for r in dispatch_rows if r.get('status')!='SKIPPED_PRE_ARM_TRADE_EXIT')
    return same_day and same_direction and 0<sequence<=baseline and not submitted
