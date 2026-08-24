from datetime import date, datetime, timedelta, timezone

import pytest

from red_bar_lab.domain.red_bar_v2 import OptionSide
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data import (
    PaperMarketQuote,
    PaperOptionInstrument,
    PaperUnderlyingQuote,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness import (
    PaperMarketDataReadinessService,
    _dominant_interval,
    _nearest_atm,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness_models import (
    ContractReadinessStatus,
    MarketDataReadinessPolicy,
    MarketDataReadinessStage,
    MarketDataReadinessStatus,
    build_probe_id,
)

NOW = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)
EXPIRY = date(2026, 8, 27)
EXPIRED = date(2026, 8, 20)
LATER_EXPIRY = date(2026, 9, 3)


class Clock:
    def now(self):
        return NOW


class Provider:
    provider_name = "UPSTOX"

    def __init__(
        self,
        *,
        missing=None,
        wide=False,
        no_depth=False,
        quote_timestamp=NOW,
        expiries=(EXPIRY,),
        ce_expiries=None,
        pe_expiries=None,
        duplicate=None,
        irregular_extra=None,
    ):
        self.missing = missing
        self.wide = wide
        self.no_depth = no_depth
        self.quote_timestamp = quote_timestamp
        self.expiries = expiries
        self.ce_expiries = ce_expiries
        self.pe_expiries = pe_expiries
        self.duplicate = duplicate
        self.irregular_extra = irregular_extra
        self.quote_calls = 0

    def underlying_quote(self, *, underlying, evaluated_at):
        return PaperUnderlyingQuote(
            "NSE_INDEX|Nifty 50",
            underlying,
            24250.0,
            NOW,
            self.provider_name,
        )

    def option_instruments(self, *, underlying, evaluated_at):
        rows = []
        side_expiries = {
            OptionSide.CE: self.ce_expiries or self.expiries,
            OptionSide.PE: self.pe_expiries or self.expiries,
        }
        for side in (OptionSide.CE, OptionSide.PE):
            for expiry in side_expiries[side]:
                for strike in range(23950, 24600, 50):
                    if self.missing == (strike, side):
                        continue
                    token = (
                        expiry.toordinal() * 1_000_000
                        + strike * 10
                        + (1 if side is OptionSide.CE else 2)
                    )
                    rows.append(
                        PaperOptionInstrument(
                            f"NSE_FO|{token}",
                            token,
                            f"NIFTY{strike}{side.value}",
                            underlying,
                            expiry,
                            float(strike),
                            side,
                            75,
                            self.provider_name,
                        )
                    )
        if self.duplicate is not None:
            strike, side = self.duplicate
            rows.append(
                PaperOptionInstrument(
                    f"NSE_FO|DUP-{strike}-{side.value}",
                    f"DUP-{strike}-{side.value}",
                    f"NIFTYDUP{strike}{side.value}",
                    underlying,
                    EXPIRY,
                    float(strike),
                    side,
                    75,
                    self.provider_name,
                )
            )
        if self.irregular_extra is not None:
            for side in (OptionSide.CE, OptionSide.PE):
                rows.append(
                    PaperOptionInstrument(
                        f"NSE_FO|EXTRA-{self.irregular_extra}-{side.value}",
                        f"EXTRA-{self.irregular_extra}-{side.value}",
                        f"NIFTYEXTRA{side.value}",
                        underlying,
                        EXPIRY,
                        float(self.irregular_extra),
                        side,
                        75,
                        self.provider_name,
                    )
                )
        return tuple(rows)

    def quotes(self, *, instrument_keys, evaluated_at):
        self.quote_calls += 1
        rows = []
        for key in instrument_keys:
            bid, ask = (
                (None, None)
                if self.no_depth
                else ((90.0, 120.0) if self.wide else (99.0, 101.0))
            )
            rows.append(
                PaperMarketQuote(
                    key,
                    key.split("|")[-1],
                    100.0,
                    bid,
                    ask,
                    self.quote_timestamp,
                    self.provider_name,
                )
            )
        return tuple(rows)


def service(provider, *, policy=None):
    return PaperMarketDataReadinessService(
        market_data=provider,
        policy=policy or MarketDataReadinessPolicy(),
        clock=Clock(),
    )


def test_interval_and_atm_rules_are_deterministic():
    assert _dominant_interval((100.0, 150.0, 200.0, 250.0)) == 50.0
    assert _dominant_interval((100.0, 125.0, 150.0, 175.0)) == 25.0
    assert _nearest_atm((100.0, 150.0), 125.0) == 100.0


def test_complete_window_is_ready_and_uses_one_quote_batch():
    provider = Provider()
    report = service(provider).evaluate(underlying="NIFTY 50")
    assert report.status is MarketDataReadinessStatus.READY
    assert report.atm_strike == 24250.0
    assert report.strike_interval == 50.0
    assert report.expected_contract_count == 18
    assert report.ready_contract_count == 18
    assert report.ce_coverage == 9 and report.pe_coverage == 9
    assert provider.quote_calls == 1
    ce_low = next(
        row
        for row in report.contracts
        if row.strike == 24050 and row.option_side is OptionSide.CE
    )
    pe_low = next(
        row
        for row in report.contracts
        if row.strike == 24050 and row.option_side is OptionSide.PE
    )
    assert ce_low.moneyness == "ITM" and pe_low.moneyness == "OTM"


def test_missing_contract_is_incomplete_without_quote_request():
    provider = Provider(missing=(24250, OptionSide.CE))
    report = service(provider).evaluate(underlying="NIFTY 50")
    assert report.status is MarketDataReadinessStatus.CHAIN_COVERAGE_INCOMPLETE
    assert provider.quote_calls == 0


@pytest.mark.parametrize("side", [OptionSide.CE, OptionSide.PE])
def test_duplicate_option_cell_is_data_corrupt(side):
    provider = Provider(duplicate=(24250, side))
    report = service(provider).evaluate(underlying="NIFTY 50")
    assert report.status is MarketDataReadinessStatus.DATA_CORRUPT
    assert report.reason_code == "DUPLICATE_OPTION_CELL"
    assert (
        report.failure_stage
        is MarketDataReadinessStage.OPTION_CONTRACT_NORMALIZATION
    )
    assert provider.quote_calls == 0


def test_option_quote_freshness_is_enforced_by_readiness_service():
    stale = Provider(quote_timestamp=NOW - timedelta(seconds=31))
    report = service(stale).evaluate(underlying="NIFTY 50")
    assert report.status is MarketDataReadinessStatus.QUOTES_STALE
    assert all(
        row.status is ContractReadinessStatus.QUOTE_STALE
        for row in report.contracts
    )

    future = Provider(quote_timestamp=NOW + timedelta(seconds=3))
    report = service(future).evaluate(underlying="NIFTY 50")
    assert report.status is MarketDataReadinessStatus.DATA_CORRUPT


def test_non_expired_common_expiry_is_selected_independently():
    provider = Provider(expiries=(EXPIRED, LATER_EXPIRY))
    report = service(provider).evaluate(underlying="NIFTY 50")
    assert report.status is MarketDataReadinessStatus.READY
    assert report.expiry == LATER_EXPIRY


def test_only_expired_contracts_are_chain_unavailable():
    provider = Provider(expiries=(EXPIRED,))
    report = service(provider).evaluate(underlying="NIFTY 50")
    assert report.status is MarketDataReadinessStatus.CHAIN_UNAVAILABLE
    assert report.reason_code == "NO_NON_EXPIRED_COMMON_EXPIRY"
    assert provider.quote_calls == 0


def test_future_ce_and_expired_pe_have_no_valid_common_expiry():
    provider = Provider(
        ce_expiries=(LATER_EXPIRY,),
        pe_expiries=(EXPIRED,),
    )
    report = service(provider).evaluate(underlying="NIFTY 50")
    assert report.status is MarketDataReadinessStatus.CHAIN_UNAVAILABLE
    assert report.reason_code == "NO_NON_EXPIRED_COMMON_EXPIRY"


def test_irregular_extra_strike_inside_window_is_corrupt():
    provider = Provider(irregular_extra=24275)
    report = service(provider).evaluate(underlying="NIFTY 50")
    assert report.status is MarketDataReadinessStatus.DATA_CORRUPT
    assert provider.quote_calls == 0


def test_coverage_policy_is_explicitly_fixed_at_nine_per_side():
    with pytest.raises(ValueError):
        service(
            Provider(),
            policy=MarketDataReadinessPolicy(min_ce_coverage=8),
        )
    with pytest.raises(ValueError):
        service(
            Provider(),
            policy=MarketDataReadinessPolicy(min_pe_coverage=8),
        )


def test_quote_quality_partial_for_missing_depth_or_wide_spread():
    report = service(Provider(no_depth=True)).evaluate(underlying="NIFTY 50")
    assert report.status is MarketDataReadinessStatus.QUOTE_QUALITY_PARTIAL
    assert all(
        row.status is ContractReadinessStatus.BID_ASK_MISSING
        for row in report.contracts
    )
    report = service(Provider(wide=True)).evaluate(underlying="NIFTY 50")
    assert report.status is MarketDataReadinessStatus.QUOTE_QUALITY_PARTIAL


def test_probe_id_is_deterministic():
    first = build_probe_id(
        provider="UPSTOX",
        underlying="NIFTY 50",
        evaluated_at=NOW,
        expiry=EXPIRY,
        atm_strike=24250.0,
    )
    second = build_probe_id(
        provider="UPSTOX",
        underlying="NIFTY 50",
        evaluated_at=NOW,
        expiry=EXPIRY,
        atm_strike=24250.0,
    )
    assert first == second
