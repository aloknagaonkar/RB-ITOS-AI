"""Offline explicit-source / clock / fail-closed acquisition regression."""
from datetime import date, datetime, timedelta

import pytest

from market_lab.domain import HistoricalCandle, HistoricalOptionContract, IST
from market_lab.hilega_milega_functional_parity_replay_v1 import (
    HistoricalParityMarketSourcesV1, HilegaMilegaHistoricalFunctionalParityReplayV1,
)
from market_lab.gateways import UpstoxGateway, GatewayError

SESSION = date(2026, 9, 23)
EXPIRY = date(2026, 9, 29)
UNDERLYING = 'NSE_INDEX|Nifty 50'


def candle(key=UNDERLYING, day=SESSION, minute=0):
    return HistoricalCandle(provider='upstox', instrument_key=key, session_date=day,
        timestamp=datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(hour=9, minute=15)
                  + timedelta(minutes=minute),
        open=23000, high=23001, low=22999, close=23000, volume=100, open_interest=None)


class Gateway:
    def __init__(self):
        self.calls = []
        self.rows = [candle(minute=i) for i in range(10)]
        self.options = [HistoricalOptionContract(instrument_key=f'CE-{s}',
            underlying=UNDERLYING, expiry=EXPIRY, strike=s, side='CE')
            for s in (22900, 22950, 23000, 23050, 23100)]

    def historical_candles(self, key, day):
        self.calls.append('historical_underlying')
        return self.rows if key == UNDERLYING and day == SESSION else []

    def intraday_candles(self, key, day):
        self.calls.append('intraday_' + key)
        if key == UNDERLYING:
            return self.rows
        return [candle(key, minute=i) for i in range(4)]

    def historical_option_contracts(self, underlying, expiry):
        self.calls.append('expired_contracts')
        return self.options

    def active_option_contracts(self, underlying, expiry):
        self.calls.append('active_contracts')
        return self.options

    def historical_option_candles(self, key, day):
        self.calls.append('expired_option_minutes')
        return [candle(key, minute=i) for i in range(4)]

    def active_option_historical_candles(self, key, day):
        self.calls.append('active_option_history')
        return [candle(key, minute=i) for i in range(4)]


def test_current_session_intraday_active_contracts_exact_option_clock():
    gateway = Gateway()
    src = HistoricalParityMarketSourcesV1(gateway, SESSION, acquisition_today=SESSION)
    assert src.underlying_source == 'UPSTOX_INTRADAY_V3'
    assert len(src._underlying) == 10
    src.option_contracts(UNDERLYING, EXPIRY)
    assert src.option_contract_source == 'UPSTOX_ACTIVE_CONTRACTS_V2'
    assert src.option_intraday_1m('CE-23000') == []
    src.nifty_intraday_1m(now=datetime(2026, 9, 23, 9, 17, 30, tzinfo=IST))
    assert len(src.option_intraday_1m('CE-23000')) == 2
    assert src.option_candle_sources['CE-23000'] == 'UPSTOX_INTRADAY_OPTION_V3'
    assert 'expired_contracts' not in gateway.calls


def test_prior_session_active_expiry_uses_history_not_intraday_or_expired():
    gateway = Gateway()
    src = HistoricalParityMarketSourcesV1(gateway, SESSION, acquisition_today=date(2026, 9, 24))
    src.option_contracts(UNDERLYING, EXPIRY)
    src.nifty_intraday_1m(now=datetime(2026, 9, 23, 9, 18, 30, tzinfo=IST))
    assert len(src.option_intraday_1m('CE-23000')) == 3
    assert src.option_candle_sources['CE-23000'] == 'UPSTOX_ACTIVE_OPTION_HISTORICAL_V3'
    assert 'expired_contracts' not in gateway.calls


def test_expired_expiry_uses_expired_catalog_and_minutes():
    gateway = Gateway()
    src = HistoricalParityMarketSourcesV1(gateway, SESSION, acquisition_today=date(2026, 10, 1))
    src.option_contracts(UNDERLYING, EXPIRY)
    src.nifty_intraday_1m(now=datetime(2026, 9, 23, 9, 18, 30, tzinfo=IST))
    src.option_intraday_1m('CE-23000')
    assert src.option_contract_source == 'UPSTOX_EXPIRED_CONTRACTS_V2'
    assert 'expired_option_minutes' in gateway.calls


def test_wrong_session_underlying_rejected():
    gateway = Gateway()
    gateway.rows = [candle(day=date(2026, 9, 22))]
    with pytest.raises(ValueError, match='CANDLE_SESSION_DATE_MISMATCH'):
        HistoricalParityMarketSourcesV1(gateway, SESSION, acquisition_today=SESSION)


def test_wrong_session_option_and_undeclared_key_rejected():
    gateway = Gateway()
    src = HistoricalParityMarketSourcesV1(gateway, SESSION, acquisition_today=SESSION)
    src.option_contracts(UNDERLYING, EXPIRY)
    with pytest.raises(ValueError, match='NOT_IN_EXACT_EXPIRY'):
        src.option_intraday_1m('CE-99999')
    gateway.intraday_candles = lambda key, day: [candle(key, day=date(2026, 9, 22))]
    with pytest.raises(ValueError, match='CANDLE_SESSION_DATE_MISMATCH'):
        src.option_intraday_1m('CE-23000')


def test_zero_session_rows_not_captured(tmp_path):
    gateway = Gateway()
    gateway.rows = []
    replay = HilegaMilegaHistoricalFunctionalParityReplayV1(gateway=gateway,
        session_date=SESSION, option_expiry=EXPIRY, output_root=tmp_path,
        warmup_calendar_days=0, acquisition_today=SESSION)
    with pytest.raises(ValueError, match='NO_TARGET_SESSION_UNDERLYING_CANDLES'):
        replay.run()


def test_gateway_intraday_rejects_other_date_before_request():
    gateway = UpstoxGateway('offline-test', client=object())
    with pytest.raises(GatewayError, match='previous session'):
        gateway.intraday_candles(UNDERLYING, date(2020, 1, 1))


def test_bootstrap_clears_prior_session_lock_without_synthetic_target_bar(tmp_path):
    from market_lab.hilega_milega_live_shadow_v1 import HilegaMilegaLiveShadowCoordinatorV1
    from market_lab.hilega_milega_strategy_v1 import SessionState

    prior = SESSION - timedelta(days=1)
    class Sources:
        def historical_candles(self, key, day):
            return [candle(key, day, minute=i) for i in range(5)] if day == prior else []
        def nifty_intraday_1m(self, *, now=None): return []
    coordinator = HilegaMilegaLiveShadowCoordinatorV1(
        market_sources=Sources(), step_audit_path=tmp_path/'audit.jsonl',
        health_path=tmp_path/'health.jsonl', cache_root=tmp_path/'cache', warmup_calendar_days=2)
    # Bootstrap constructs fresh engine and should retain actual historical indicator warmup.
    out = coordinator.bootstrap(datetime(2026, 9, 23, 9, 15, 30, tzinfo=IST))
    assert out['state'] != 'SESSION_LOCKED'
    assert coordinator.strategy.session.session_date == SESSION
    assert coordinator.strategy.indicators._last_close == 23000
    assert coordinator.strategy.previous_bar is None
