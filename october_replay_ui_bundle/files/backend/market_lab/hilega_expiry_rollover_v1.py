"""Automatic option expiry selection; manual mode is explicit and guarded."""
import os
from datetime import date

def resolve_expiry(sources, *, session_date, configured_raw=''):
    mode = os.getenv('HILEGA_OPTION_EXPIRY_MODE', 'AUTO').strip().upper()
    if mode not in {'AUTO', 'MANUAL'}:
        raise ValueError('HILEGA_OPTION_EXPIRY_MODE must be AUTO or MANUAL')
    if mode == 'MANUAL':
        expiry = date.fromisoformat(configured_raw.strip())
        if expiry < session_date:
            raise ValueError('Manual option expiry is expired; use AUTO or a valid date')
        return expiry, 'EXPLICIT_MANUAL_EXPIRY'
    expiry = sources.resolve_option_expiry('NSE_INDEX|Nifty 50', today=session_date)
    if expiry is None or expiry < session_date:
        raise ValueError('No valid unexpired option contract returned')
    return expiry, 'AUTO_UPSTOX_INSTRUMENT_SEARCH'
