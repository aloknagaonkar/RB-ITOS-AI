"""Resolve the approved legacy configuration to the promoted native policy.

Only the legacy alignment selection is mapped. Journal identities are never
rewritten; execution modes and every other configuration value are untouched.
"""
CONFIGURED_ALIGNMENT_ID='HILEGA_V2_ALIGNMENT_DUAL_EXIT'
ACTIVE_RSI_ID='HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT'

def effective_strategy(value):
    if isinstance(value,str) and value.strip().upper()==CONFIGURED_ALIGNMENT_ID:
        return ACTIVE_RSI_ID
    return value
