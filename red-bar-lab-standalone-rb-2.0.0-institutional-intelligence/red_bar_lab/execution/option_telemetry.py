from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
RSI_STRATEGY_SOURCE = 'RSI_EXTREME_REVERSAL_V1'
OBSERVATIONAL_AUTHORITY = 'OBSERVATIONAL_ONLY'


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_level(depth: object, side: str) -> dict[str, object]:
    if not isinstance(depth, dict):
        return {}
    levels = depth.get(side) or []
    if not levels or not isinstance(levels[0], dict):
        return {}
    return levels[0]


def classify_option_support(*, premium_return_pct, oi_change, relative_volume, spread_pct):
    available = [v for v in (premium_return_pct, oi_change, relative_volume, spread_pct) if v is not None]
    if not available:
        return 'NOT_AVAILABLE', 'No usable premium/OI/volume/spread evidence.'
    reasons = []
    supportive = 0
    conflicting = 0
    if premium_return_pct is not None:
        if premium_return_pct > 0:
            supportive += 1; reasons.append('PREMIUM_POSITIVE')
        elif premium_return_pct < 0:
            conflicting += 1; reasons.append('PREMIUM_NEGATIVE')
        else:
            reasons.append('PREMIUM_FLAT')
    if oi_change is not None:
        if oi_change > 0:
            supportive += 1; reasons.append('OI_BUILDUP')
        elif oi_change < 0:
            reasons.append('OI_UNWINDING')
        else:
            reasons.append('OI_FLAT')
    if relative_volume is not None:
        if relative_volume >= 1.2:
            supportive += 1; reasons.append('VOLUME_EXPANSION')
        elif relative_volume < 0.7:
            conflicting += 1; reasons.append('VOLUME_WEAK')
        else:
            reasons.append('VOLUME_NORMAL')
    if spread_pct is not None:
        if spread_pct > 2.0:
            conflicting += 1; reasons.append('SPREAD_WIDE')
        else:
            reasons.append('SPREAD_ACCEPTABLE')
    if supportive >= 2 and conflicting == 0:
        classification = 'SUPPORTED'
    elif conflicting >= 2 and supportive == 0:
        classification = 'CONFLICT'
    else:
        classification = 'NEUTRAL'
    return classification, '|'.join(reasons)


@dataclass(frozen=True)
class TelemetryCaptureResult:
    captured: int
    skipped: int
    errors: tuple[str, ...]


class OptionExecutionTelemetryService:
    def __init__(self, database, *, account_id: str):
        self.database = database
        self.account_id = str(account_id)

    def capture(self, *, market_data, now: datetime | None = None) -> TelemetryCaptureResult:
        observed = (now or datetime.now(IST)).astimezone(IST)
        captured = 0
        skipped = 0
        errors = []
        orders = self.database.read_paper_execution_orders(self.account_id)
        rsi_orders = [o for o in orders if str(o.get('execution_strategy_source') or '') == RSI_STRATEGY_SOURCE]
        if not rsi_orders:
            return TelemetryCaptureResult(0, 0, ())
        keys = [f"{o.get('exchange')}:{o.get('tradingsymbol')}" for o in rsi_orders if o.get('exchange') and o.get('tradingsymbol')]
        try:
            quotes = market_data.quote(keys) if keys else {}
        except Exception as exc:
            return TelemetryCaptureResult(0, len(rsi_orders), (f'QUOTE_BATCH:{type(exc).__name__}:{exc}',))

        for order in rsi_orders:
            try:
                order_id = str(order.get('order_id') or '')
                key = f"{order.get('exchange')}:{order.get('tradingsymbol')}"
                quote = quotes.get(key) or {}
                if not order_id or not quote:
                    skipped += 1
                    continue
                latest = self.database.read_latest_option_execution_telemetry(order_id)
                current_price = _num(quote.get('last_price'), _num(order.get('current_price')))
                entry_price = _num(order.get('entry_price'))
                volume = _num(quote.get('volume'))
                oi = _num(quote.get('oi'))
                previous_volume = _num((latest or {}).get('volume'))
                previous_oi = _num((latest or {}).get('oi'))
                volume_change = volume - previous_volume if volume is not None and previous_volume is not None else None
                oi_change = oi - previous_oi if oi is not None and previous_oi is not None else None
                oi_change_pct = oi_change / previous_oi * 100.0 if oi_change is not None and previous_oi not in (None, 0.0) else None
                premium_return_pct = ((current_price - entry_price) / entry_price * 100.0 if current_price is not None and entry_price not in (None, 0.0) else None)
                depth = quote.get('depth') or {}
                bid = _first_level(depth, 'buy')
                ask = _first_level(depth, 'sell')
                best_bid = _num(bid.get('price'))
                best_ask = _num(ask.get('price'))
                spread_points = best_ask - best_bid if best_ask is not None and best_bid is not None else None
                midpoint = (best_ask + best_bid) / 2.0 if best_ask is not None and best_bid is not None else None
                spread_pct = spread_points / midpoint * 100.0 if spread_points is not None and midpoint not in (None, 0.0) else None
                relative_volume = volume / previous_volume if volume is not None and previous_volume not in (None, 0.0) else None
                classification, reason = classify_option_support(
                    premium_return_pct=premium_return_pct,
                    oi_change=oi_change,
                    relative_volume=relative_volume,
                    spread_pct=spread_pct,
                )
                raw_id = f"{order_id}|{observed.isoformat()}|{quote.get('last_price')}|{quote.get('oi')}|{quote.get('volume')}"
                telemetry_id = 'OT-' + sha1(raw_id.encode('utf-8')).hexdigest()[:20].upper()
                self.database.insert_option_execution_telemetry({
                    'telemetry_id': telemetry_id,
                    'order_id': order_id,
                    'signal_id': order.get('signal_id'),
                    'execution_strategy_source': RSI_STRATEGY_SOURCE,
                    'observed_timestamp': observed.isoformat(),
                    'exchange': order.get('exchange'),
                    'tradingsymbol': order.get('tradingsymbol'),
                    'instrument_token': order.get('instrument_token'),
                    'option_type': order.get('option_type'),
                    'strike': order.get('strike'),
                    'expiry': order.get('expiry'),
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'premium_return_pct': premium_return_pct,
                    'volume': volume,
                    'volume_change': volume_change,
                    'relative_volume': relative_volume,
                    'oi': oi,
                    'oi_change': oi_change,
                    'oi_change_pct': oi_change_pct,
                    'best_bid': best_bid,
                    'best_ask': best_ask,
                    'spread_points': spread_points,
                    'spread_pct': spread_pct,
                    'buy_quantity': _num(quote.get('buy_quantity')),
                    'sell_quantity': _num(quote.get('sell_quantity')),
                    'iv': _num(quote.get('iv')),
                    'delta': _num(quote.get('delta')),
                    'gamma': _num(quote.get('gamma')),
                    'theta': _num(quote.get('theta')),
                    'vega': _num(quote.get('vega')),
                    'pcr_oi': None,
                    'pcr_source': 'NOT_AVAILABLE',
                    'support_classification': classification,
                    'support_reason': reason,
                    'authority': OBSERVATIONAL_AUTHORITY,
                    'created_at': observed.isoformat(),
                })
                captured += 1
            except Exception as exc:
                errors.append(f"{order.get('order_id')}:{type(exc).__name__}:{exc}")
        return TelemetryCaptureResult(captured, skipped, tuple(errors))
