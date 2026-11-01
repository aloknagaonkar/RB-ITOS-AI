from datetime import date, datetime, timezone
import httpx
import pytest
from market_lab.domain import PCRConfig
from market_lab.gateways import GatewayError, UpstoxGateway, normalize_upstox, parse_timestamp

NOW = datetime(2026, 9, 9, 4, 0, tzinfo=timezone.utc)


def payload():
    c = PCRConfig(provider="upstox", expiry=date(2026, 9, 15), wings=0)
    common = {"underlying_key": c.underlying, "expiry": "2026-09-15", "strike_price": 25000}
    catalog = {
        "status": "success",
        "data": [
            dict(common, instrument_key="NSE_FO|1", instrument_type="CE"),
            dict(common, instrument_key="NSE_FO|2", instrument_type="PE"),
        ],
    }
    chain = {
        "status": "success",
        "data": [
            dict(
                common,
                call_options={"instrument_key": "NSE_FO|1", "market_data": {
                    "oi": 100, "prev_oi": 80, "ltp": 125.5, "bid_price": 125,
                    "ask_price": 126, "volume": 1000,
                }},
                put_options={"instrument_key": "NSE_FO|2", "market_data": {
                    "oi": 150, "prev_oi": 120, "ltp": 110, "bid_price": 109.5,
                    "ask_price": 110.5, "volume": 900,
                }},
            )
        ],
    }
    spot = {
        "status": "success",
        "data": {
            "NSE_INDEX:Nifty 50": {
                "instrument_token": c.underlying,
                "last_price": 25000,
                "timestamp": NOW.isoformat(),
            }
        },
    }
    return c, catalog, chain, spot


def test_normalize():
    c, catalog, chain, spot = payload()
    s = normalize_upstox(c, catalog, chain, spot, NOW, NOW)
    assert [q.oi for q in s.quotes] == [100, 150]
    assert [q.prev_oi for q in s.quotes] == [80, 120]
    assert [q.ltp for q in s.quotes] == [125.5, 110]
    assert [q.bid for q in s.quotes] == [125, 109.5]
    assert [q.ask for q in s.quotes] == [126, 110.5]
    assert [q.volume for q in s.quotes] == [1000, 900]
    assert all(q.quote_timestamp is None for q in s.quotes)
    assert s.oi_source_at is None and s.spot_feed_at == NOW and s.raw["catalog"] == catalog


@pytest.mark.parametrize("field,bad", [("ltp", -1), ("bid_price", "125"), ("ask_price", True), ("volume", 1.2)])
def test_invalid_market_data_stays_unavailable(field, bad):
    c, catalog, chain, spot = payload()
    chain["data"][0]["call_options"]["market_data"][field] = bad
    quote = normalize_upstox(c, catalog, chain, spot, NOW, NOW).quotes[0]
    normalized = {"ltp": quote.ltp, "bid_price": quote.bid, "ask_price": quote.ask, "volume": quote.volume}
    assert normalized[field] is None


@pytest.mark.parametrize("bad", [None, -1, 1.2, True, "100"])
def test_invalid_oi(bad):
    c, catalog, chain, spot = payload()
    chain["data"][0]["put_options"]["market_data"]["oi"] = bad
    assert normalize_upstox(c, catalog, chain, spot, NOW, NOW).quotes[1].oi is None


@pytest.mark.parametrize("bad", [None, -1, 1.2, True, "100"])
def test_invalid_previous_oi_stays_unavailable(bad):
    c, catalog, chain, spot = payload()
    chain["data"][0]["put_options"]["market_data"]["prev_oi"] = bad
    assert normalize_upstox(c, catalog, chain, spot, NOW, NOW).quotes[1].prev_oi is None


def test_mismatched_contract():
    c, catalog, chain, spot = payload()
    chain["data"][0]["strike_price"] = 25100
    with pytest.raises(ValueError, match="identity"):
        normalize_upstox(c, catalog, chain, spot, NOW, NOW)


@pytest.mark.parametrize(
    "status,part", [(401, "authentication"), (403, "authentication"), (429, "rate limit"), (503, "HTTP 503")]
)
def test_sanitized_http_errors(status, part):
    with httpx.Client(
        base_url="https://api.upstox.com",
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="secret-token")),
    ) as client:
        with pytest.raises(GatewayError, match=part) as error:
            UpstoxGateway("secret-token", client).collect(payload()[0])
        assert "secret-token" not in str(error.value)


def test_read_endpoints():
    c, catalog, chain, spot = payload()
    bodies = {"/v2/option/contract": catalog, "/v2/option/chain": chain, "/v2/market-quote/quotes": spot}
    paths = []

    def handler(request):
        assert request.method == "GET" and request.headers["Authorization"] == "Bearer local-test-token"
        assert request.url.params["instrument_key"] == c.underlying
        paths.append(request.url.path)
        return httpx.Response(200, json=bodies[request.url.path])

    with httpx.Client(base_url="https://api.upstox.com", transport=httpx.MockTransport(handler)) as client:
        assert UpstoxGateway("local-test-token", client).collect(c).spot == 25000
    assert paths == list(bodies)


def test_timestamp_formats():
    assert parse_timestamp(int(NOW.timestamp() * 1000)) == NOW
    assert parse_timestamp(NOW.isoformat()) == NOW
    assert parse_timestamp("2026-09-09T04:00:00") is None
    assert parse_timestamp("invalid") is None


def test_timeout_and_malformed_json():
    def timeout(request):
        raise httpx.ReadTimeout("secret-token", request=request)

    for handler in [timeout, lambda _: httpx.Response(200, text="not-json")]:
        with httpx.Client(
            base_url="https://api.upstox.com", transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(GatewayError) as error:
                UpstoxGateway("secret-token", client).collect(payload()[0])
            assert "secret-token" not in str(error.value)
