from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from red_bar_lab.execution.option_telemetry import (
    OBSERVATIONAL_AUTHORITY,
    OptionExecutionTelemetryService,
    classify_option_support,
)

IST = ZoneInfo('Asia/Kolkata')


class FakeDatabase:
    def __init__(self, orders, latest=None):
        self.orders = orders
        self.latest = latest or {}
        self.rows = []
    def read_paper_execution_orders(self, account_id):
        return list(self.orders)
    def read_latest_option_execution_telemetry(self, order_id):
        return self.latest.get(order_id)
    def insert_option_execution_telemetry(self, row):
        self.rows.append(dict(row))


class FakeMarketData:
    def __init__(self, quotes):
        self.quotes = quotes
    def quote(self, keys):
        return {k: self.quotes[k] for k in keys if k in self.quotes}


def _order(source='RSI_EXTREME_REVERSAL_V1'):
    return {
        'order_id': 'PAPER-1', 'account_id': 'PAPER-STD',
        'signal_id': 'RSI7-TEST', 'execution_strategy_source': source,
        'exchange': 'NFO', 'tradingsymbol': 'NIFTY26AUG25000CE',
        'instrument_token': 123, 'option_type': 'CE', 'strike': 25000.0,
        'expiry': '2026-08-27', 'entry_price': 100.0, 'current_price': 100.0,
    }


def test_support_classifier_is_supported():
    classification, reason = classify_option_support(
        premium_return_pct=5.0, oi_change=1000.0,
        relative_volume=1.5, spread_pct=0.5,
    )
    assert classification == 'SUPPORTED'
    assert 'PREMIUM_POSITIVE' in reason
    assert 'OI_BUILDUP' in reason


def test_support_classifier_conflict():
    classification, reason = classify_option_support(
        premium_return_pct=-4.0, oi_change=0.0,
        relative_volume=0.5, spread_pct=3.0,
    )
    assert classification == 'CONFLICT'
    assert 'PREMIUM_NEGATIVE' in reason
    assert 'VOLUME_WEAK' in reason
    assert 'SPREAD_WIDE' in reason


def test_capture_writes_raw_rsi_contract_telemetry():
    db = FakeDatabase([_order()], latest={'PAPER-1': {'volume': 10000.0, 'oi': 50000.0}})
    market = FakeMarketData({'NFO:NIFTY26AUG25000CE': {
        'last_price': 106.0, 'volume': 15000, 'oi': 52000,
        'buy_quantity': 500, 'sell_quantity': 450,
        'iv': 12.5, 'delta': 0.55, 'gamma': 0.001,
        'theta': -4.0, 'vega': 8.0,
        'depth': {'buy': [{'price': 105.5}], 'sell': [{'price': 106.0}]},
    }})
    result = OptionExecutionTelemetryService(db, account_id='PAPER-STD').capture(
        market_data=market,
        now=datetime(2026, 8, 17, 10, 30, tzinfo=IST),
    )
    assert result.captured == 1
    assert not result.errors
    row = db.rows[0]
    assert row['premium_return_pct'] == 6.0
    assert row['oi_change'] == 2000.0
    assert row['volume_change'] == 5000.0
    assert row['relative_volume'] == 1.5
    assert row['best_bid'] == 105.5
    assert row['best_ask'] == 106.0
    assert row['support_classification'] == 'SUPPORTED'
    assert row['authority'] == OBSERVATIONAL_AUTHORITY
    assert row['pcr_source'] == 'NOT_AVAILABLE'


def test_non_rsi_orders_are_not_captured():
    db = FakeDatabase([_order(source='REFERENCE_LEVEL')])
    result = OptionExecutionTelemetryService(db, account_id='PAPER-STD').capture(
        market_data=FakeMarketData({}),
        now=datetime(2026, 8, 17, 10, 30, tzinfo=IST),
    )
    assert result.captured == 0
    assert not db.rows


def test_missing_quote_is_skipped_without_error():
    db = FakeDatabase([_order()])
    result = OptionExecutionTelemetryService(db, account_id='PAPER-STD').capture(
        market_data=FakeMarketData({}),
        now=datetime(2026, 8, 17, 10, 30, tzinfo=IST),
    )
    assert result.captured == 0
    assert result.skipped == 1
    assert not result.errors
