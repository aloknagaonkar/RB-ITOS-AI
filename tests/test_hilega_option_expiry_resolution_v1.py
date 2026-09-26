from datetime import date

import pytest

from market_lab.live_shadow_worker_v1 import (
    _resolve_hilega_option_expiry,
)
from market_lab.upstox_live_shadow_sources_v1 import (
    UpstoxLiveShadowSourcesV1,
)


UNDERLYING = "NSE_INDEX|Nifty 50"


class Gateway:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def _get(self, path, *, params=None):
        self.calls.append((path, params))
        return {
            "status": "success",
            "data": list(self.rows),
        }

    def close(self):
        pass


def source(rows):
    s = object.__new__(UpstoxLiveShadowSourcesV1)
    s.gateway = Gateway(rows)
    return s


def option(expiry, *, side="CE", underlying=UNDERLYING):
    return {
        "segment": "NSE_FO",
        "underlying_key": underlying,
        "underlying_symbol": "NIFTY",
        "instrument_type": side,
        "expiry": expiry,
        "instrument_key": f"{side}-{expiry}",
    }


def test_auto_resolver_selects_nearest_valid_expiry():
    s = source([
        option("2026-10-06"),
        option("2026-09-29", side="PE"),
        option("2026-09-29"),
    ])

    got = s.resolve_option_expiry(
        UNDERLYING,
        today=date(2026, 9, 25),
    )

    assert got == date(2026, 9, 29)

    assert len(s.gateway.calls) == 4

    assert [
        params["expiry"]
        for path, params in s.gateway.calls
    ] == [
        "current_week",
        "next_week",
        "current_month",
        "next_month",
    ]

    for path, params in s.gateway.calls:
        assert path == "/v2/instruments/search"
        assert params["query"] == "NIFTY"
        assert params["instrument_types"] == "CE,PE"


def test_auto_resolver_rejects_past_and_wrong_identity():
    s = source([
        option("2026-09-22"),
        option(
            "2026-09-29",
            underlying="NSE_INDEX|Nifty Bank",
        ),
        {
            **option("2026-09-29"),
            "underlying_symbol": "BANKNIFTY",
        },
        {
            **option("2026-09-29"),
            "instrument_type": "FUT",
        },
        option("2026-10-06"),
    ])

    got = s.resolve_option_expiry(
        UNDERLYING,
        today=date(2026, 9, 25),
    )

    assert got == date(2026, 10, 6)


def test_auto_resolver_fails_closed_when_none_valid():
    s = source([
        option("2026-09-22"),
    ])

    with pytest.raises(
        ValueError,
        match="NO_VALID_NIFTY_OPTION_EXPIRY",
    ):
        s.resolve_option_expiry(
            UNDERLYING,
            today=date(2026, 9, 25),
        )


def test_configured_expiry_is_exact_override():
    class Sources:
        def resolve_option_expiry(self, *args, **kwargs):
            raise AssertionError(
                "provider resolver must not run for configured expiry"
            )

    expiry, source_name = _resolve_hilega_option_expiry(
        Sources(),
        session_date=date(2026, 9, 25),
        configured_raw="2026-09-29",
    )

    assert expiry == date(2026, 9, 29)
    assert source_name == "CONFIGURED_ENV"


def test_missing_config_uses_provider_resolution():
    calls = []

    class Sources:
        def resolve_option_expiry(
            self,
            underlying,
            *,
            today,
        ):
            calls.append((underlying, today))
            return date(2026, 9, 29)

    expiry, source_name = _resolve_hilega_option_expiry(
        Sources(),
        session_date=date(2026, 9, 25),
        configured_raw="",
    )

    assert expiry == date(2026, 9, 29)
    assert source_name == "AUTO_UPSTOX_INSTRUMENT_SEARCH"

    assert calls == [
        (
            UNDERLYING,
            date(2026, 9, 25),
        )
    ]
