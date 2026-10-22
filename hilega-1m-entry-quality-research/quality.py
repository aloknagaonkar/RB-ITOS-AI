"""Research-only entry filters. Thresholds are hypotheses, not fitted optima."""
import math

VARIANTS = ('RSI_EMA50', 'WMA50', 'EMA10_SLOPE3', 'EMA10_DISTANCE30')

def assess(side, frame, variant):
    sign = 1 if side == 'BULLISH' else -1
    keys = ('rsi9', 'ema3_rsi', 'wma21_rsi', 'close', 'ema10', 'previous_ema10')
    if any(not isinstance(frame.get(k), (int, float)) or isinstance(frame.get(k), bool) or not math.isfinite(frame[k]) for k in keys):
        return {'passed': False, 'variant': variant, 'reason': 'QUALITY_VALUES_MISSING'}
    slope = sign * (frame['ema10'] - frame['previous_ema10'])
    distance = sign * (frame['close'] - frame['ema10'])
    rules = {
        'RSI_EMA50': sign*(frame['rsi9']-50)>0 and sign*(frame['ema3_rsi']-50)>0,
        'WMA50': sign*(frame['wma21_rsi']-50)>0,
        'EMA10_SLOPE3': slope >= 3,
        'EMA10_DISTANCE30': 0 < distance <= 30,
    }
    if variant not in rules: raise ValueError('UNKNOWN_QUALITY_VARIANT:'+variant)
    return dict(passed=rules[variant], variant=variant, directional_ema10_slope=slope,
                directional_ema10_distance=distance, reason='PASS' if rules[variant] else variant+'_FAILED')
