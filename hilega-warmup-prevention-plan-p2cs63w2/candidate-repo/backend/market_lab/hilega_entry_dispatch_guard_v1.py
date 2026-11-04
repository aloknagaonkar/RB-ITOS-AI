"""Reject delayed new BUY submissions, never delay a position exit."""
from datetime import datetime

MAX_ENTRY_DISPATCH_AGE_SECONDS = 120

def entry_dispatch_check(signal_time, evaluated_at, session_date):
    result = dict(signal_time=signal_time, evaluated_at=evaluated_at.isoformat(),
                  max_age_seconds=MAX_ENTRY_DISPATCH_AGE_SECONDS,
                  policy_version='ENTRY_DISPATCH_FRESHNESS_V1')
    try:
        signal = datetime.fromisoformat(signal_time)
        if signal.utcoffset() is None or evaluated_at.utcoffset() is None:
            raise ValueError('timezone required')
        age = (evaluated_at - signal).total_seconds()
        result['age_seconds'] = age
        local_signal = signal.astimezone(evaluated_at.tzinfo)
        if local_signal.date().isoformat() != session_date:
            reason = 'ENTRY_SESSION_DATE_MISMATCH'
        elif age < 0:
            reason = 'ENTRY_TIMESTAMP_IN_FUTURE'
        elif age > MAX_ENTRY_DISPATCH_AGE_SECONDS:
            reason = 'STALE_ENTRY_DISPATCH'
        else:
            reason = None
    except (TypeError, ValueError, OverflowError):
        reason = 'INVALID_ENTRY_TIMESTAMP'
    result.update(passed=reason is None, reason=reason)
    return result
