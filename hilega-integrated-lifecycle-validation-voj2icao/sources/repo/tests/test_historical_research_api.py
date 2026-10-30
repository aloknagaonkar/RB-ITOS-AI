from datetime import date, datetime

from fastapi.testclient import TestClient

from market_lab.api import create_app
from market_lab.domain import HistoricalCandle, HistoricalOptionContract, IST
from market_lab.storage import initialize, make_engine

UNDERLYING = "NSE_INDEX|Nifty 50"
SESSION = date(2026, 9, 8)
EXPIRY = date(2026, 9, 8)


def candle(key, minute, close, oi=None):
    return HistoricalCandle(
        provider="upstox",
        instrument_key=key,
        session_date=SESSION,
        timestamp=datetime(2026, 9, 8, 9, minute, tzinfo=IST),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=100,
        open_interest=oi,
    )


def contract(strike, side):
    return HistoricalOptionContract(
        instrument_key=f"{side}-{int(strike)}",
        underlying=UNDERLYING,
        expiry=EXPIRY,
        strike=strike,
        side=side,
        lot_size=75,
        is_weekly=True,
    )


class GatewayStub:
    def __init__(self):
        self.underlying = [
            candle(UNDERLYING, 19, 23249),
            candle(UNDERLYING, 20, 23276),
            candle(UNDERLYING, 21, 23330),
        ]
        self.contracts = [
            contract(strike, side)
            for strike in (23250, 23300, 23350)
            for side in ("CE", "PE")
        ]
        self.options = {
            item.instrument_key: [
                candle(
                    item.instrument_key,
                    minute,
                    100 if item.side == "CE" else 120,
                    1000 if item.side == "CE" else 1500,
                )
                for minute in (19, 20, 21)
            ]
            for item in self.contracts
        }

    def historical_candles(self, instrument_key, session_date):
        return self.underlying if instrument_key == UNDERLYING else []

    def historical_option_contracts(self, underlying, expiry):
        return self.contracts

    def historical_option_candles(self, instrument_key, session_date):
        return self.options.get(instrument_key, [])


def make_client(tmp_path, gateway):
    engine = make_engine("sqlite:///" + (tmp_path / "historical-api.db").as_posix())
    initialize(engine)
    return TestClient(create_app(engine, historical_gateway_factory=lambda: gateway)), engine


def test_historical_research_api_returns_timeline_and_three_panels(tmp_path):
    client, engine = make_client(tmp_path, GatewayStub())
    with client:
        response = client.get(
            "/api/research/historical/pcr",
            params={
                "underlying": UNDERLYING,
                "session_date": SESSION.isoformat(),
                "expiry": EXPIRY.isoformat(),
                "wings": 0,
            },
        )
    engine.dispose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "AVAILABLE"
    assert payload["provenance"] == "HISTORICAL_CANDLE_RECONSTRUCTION"
    assert len(payload["observations"]) == 3
    before, anchor, after = payload["observations"]
    assert before["fixed_panel"]["status"] == "UNAVAILABLE"
    assert anchor["fixed_panel"]["status"] == "AVAILABLE"
    assert anchor["fixed_panel"]["atm"] == 23300.0
    assert after["fixed_panel"]["atm"] == 23300.0
    assert after["moving_panel"]["atm"] == 23350.0
    assert anchor["moving_panel"]["pcr"] == 1.5
    assert anchor["full_reconstructed_panel"]["pcr"] == 1.5
    assert anchor["strike_results"][0]["call_oi"] == 1000
    assert anchor["strike_results"][0]["put_oi"] == 1500


def test_historical_research_api_validates_wings(tmp_path):
    client, engine = make_client(tmp_path, GatewayStub())
    with client:
        response = client.get(
            "/api/research/historical/pcr",
            params={
                "underlying": UNDERLYING,
                "session_date": SESSION.isoformat(),
                "expiry": EXPIRY.isoformat(),
                "wings": -1,
            },
        )
    engine.dispose()
    assert response.status_code == 422


def test_historical_research_api_returns_unavailable_for_empty_session(tmp_path):
    gateway = GatewayStub()
    gateway.underlying = []
    client, engine = make_client(tmp_path, gateway)
    with client:
        response = client.get(
            "/api/research/historical/pcr",
            params={
                "underlying": UNDERLYING,
                "session_date": SESSION.isoformat(),
                "expiry": EXPIRY.isoformat(),
                "wings": 5,
            },
        )
    engine.dispose()
    assert response.status_code == 200
    assert response.json()["status"] == "UNAVAILABLE"
    assert response.json()["issues"] == ["underlying_candles_unavailable"]
    assert response.json()["observations"] == []
