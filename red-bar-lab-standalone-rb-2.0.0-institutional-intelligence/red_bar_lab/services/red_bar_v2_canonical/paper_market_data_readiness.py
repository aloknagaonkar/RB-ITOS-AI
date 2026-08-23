from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from math import isclose
from typing import Protocol

from red_bar_lab.domain.red_bar_v2 import OptionSide

from .paper_market_data import (
    PaperCanaryMarketData,
    PaperMarketDataAuthenticationError,
    PaperMarketDataCorruptionError,
    PaperMarketDataRateLimitError,
    PaperMarketDataStaleError,
    PaperMarketDataUnavailableError,
    verify_timestamp_freshness,
)
from .paper_market_data_readiness_models import (
    ContractReadinessEvidence,
    ContractReadinessStatus,
    MarketDataReadinessPolicy,
    MarketDataReadinessReport,
    MarketDataReadinessStatus,
    build_probe_id,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now().astimezone()


def _dominant_interval(strikes: tuple[float, ...]) -> float:
    unique = sorted(set(float(value) for value in strikes))
    if len(unique) < 3:
        raise PaperMarketDataCorruptionError("insufficient strikes for interval")
    differences = [
        round(unique[index + 1] - unique[index], 8)
        for index in range(len(unique) - 1)
    ]
    positive = [value for value in differences if value > 0]
    if not positive:
        raise PaperMarketDataCorruptionError("invalid strike interval")
    counts = Counter(positive)
    highest = max(counts.values())
    modes = sorted(value for value, count in counts.items() if count == highest)
    if len(modes) != 1 or highest < 2:
        raise PaperMarketDataCorruptionError("ambiguous or irregular strike interval")
    return modes[0]


def _nearest_atm(strikes: tuple[float, ...], spot: float) -> float:
    if not strikes:
        raise PaperMarketDataCorruptionError("ATM strike unavailable")
    return min(
        set(float(value) for value in strikes),
        key=lambda value: (abs(value - spot), value),
    )


def _moneyness(side: OptionSide, distance_steps: int) -> str:
    if distance_steps == 0:
        return "ATM"
    if side is OptionSide.CE:
        return "ITM" if distance_steps < 0 else "OTM"
    return "OTM" if distance_steps < 0 else "ITM"


class PaperMarketDataReadinessService:
    def __init__(
        self,
        *,
        market_data: PaperCanaryMarketData,
        policy: MarketDataReadinessPolicy,
        clock: Clock,
    ) -> None:
        self.market_data = market_data
        self.policy = policy
        self.clock = clock
        if policy.strike_steps != 4:
            raise ValueError("readiness strike_steps must be exactly 4")
        if policy.min_ce_coverage != 9 or policy.min_pe_coverage != 9:
            raise ValueError("readiness CE and PE coverage must each be exactly 9")

    def _report(
        self,
        *,
        evaluated_at: datetime,
        underlying: str,
        status: MarketDataReadinessStatus,
        reason: str,
        underlying_key: str | None = None,
        spot: float | None = None,
        spot_timestamp: datetime | None = None,
        expiry=None,
        interval: float | None = None,
        atm: float | None = None,
        contracts=(),
    ) -> MarketDataReadinessReport:
        evidence = tuple(contracts)
        expected = 18 if expiry is not None and atm is not None else 0
        return MarketDataReadinessReport(
            probe_id=build_probe_id(
                provider=self.market_data.provider_name,
                underlying=underlying,
                evaluated_at=evaluated_at,
                expiry=expiry,
                atm_strike=atm,
            ),
            provider=self.market_data.provider_name,
            underlying=underlying,
            underlying_instrument_key=underlying_key,
            evaluated_at=evaluated_at,
            spot_price=spot,
            spot_timestamp=spot_timestamp,
            expiry=expiry,
            strike_interval=interval,
            atm_strike=atm,
            expected_contract_count=expected,
            observed_contract_count=len(evidence),
            ready_contract_count=sum(
                item.status is ContractReadinessStatus.READY
                for item in evidence
            ),
            ce_coverage=sum(
                item.option_side is OptionSide.CE for item in evidence
            ),
            pe_coverage=sum(
                item.option_side is OptionSide.PE for item in evidence
            ),
            status=status,
            reason_code=reason,
            contracts=evidence,
        )

    def _spot_failure(
        self,
        *,
        evaluated_at: datetime,
        underlying: str,
        status: MarketDataReadinessStatus,
        reason: str,
    ) -> MarketDataReadinessReport:
        return self._report(
            evaluated_at=evaluated_at,
            underlying=underlying,
            status=status,
            reason=reason,
        )

    def evaluate(self, *, underlying: str) -> MarketDataReadinessReport:
        evaluated_at = self.clock.now()
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("readiness clock must be timezone-aware")

        try:
            spot_quote = self.market_data.underlying_quote(
                underlying=underlying,
                evaluated_at=evaluated_at,
            )
            if (
                spot_quote.provider != self.market_data.provider_name
                or spot_quote.underlying != underlying
            ):
                raise PaperMarketDataCorruptionError("underlying identity mismatch")
            verify_timestamp_freshness(
                timestamp=spot_quote.quote_timestamp,
                evaluated_at=evaluated_at,
                maximum_age_seconds=self.policy.max_quote_age_seconds,
            )
        except PaperMarketDataAuthenticationError:
            return self._spot_failure(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.AUTHENTICATION_FAILED,
                reason="AUTHENTICATION_FAILED",
            )
        except PaperMarketDataRateLimitError:
            return self._spot_failure(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.RATE_LIMITED,
                reason="RATE_LIMITED",
            )
        except PaperMarketDataUnavailableError:
            return self._spot_failure(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.SPOT_UNAVAILABLE,
                reason="SPOT_UNAVAILABLE",
            )
        except (PaperMarketDataCorruptionError, ValueError, TypeError):
            return self._spot_failure(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.DATA_CORRUPT,
                reason="DATA_CORRUPT",
            )

        common = dict(
            evaluated_at=evaluated_at,
            underlying=underlying,
            underlying_key=spot_quote.instrument_key,
            spot=spot_quote.last_price,
            spot_timestamp=spot_quote.quote_timestamp,
        )
        try:
            instruments = self.market_data.option_instruments(
                underlying=underlying,
                evaluated_at=evaluated_at,
            )
        except PaperMarketDataAuthenticationError:
            return self._report(
                **common,
                status=MarketDataReadinessStatus.AUTHENTICATION_FAILED,
                reason="AUTHENTICATION_FAILED",
            )
        except PaperMarketDataRateLimitError:
            return self._report(
                **common,
                status=MarketDataReadinessStatus.RATE_LIMITED,
                reason="RATE_LIMITED",
            )
        except PaperMarketDataUnavailableError:
            return self._report(
                **common,
                status=MarketDataReadinessStatus.PROVIDER_UNAVAILABLE,
                reason="PROVIDER_UNAVAILABLE",
            )
        except (PaperMarketDataCorruptionError, ValueError, TypeError):
            return self._report(
                **common,
                status=MarketDataReadinessStatus.DATA_CORRUPT,
                reason="DATA_CORRUPT",
            )
        if not instruments:
            return self._report(
                **common,
                status=MarketDataReadinessStatus.CHAIN_UNAVAILABLE,
                reason="CHAIN_UNAVAILABLE",
            )

        try:
            ce_expiries = {
                item.expiry for item in instruments
                if item.option_side is OptionSide.CE
            }
            pe_expiries = {
                item.expiry for item in instruments
                if item.option_side is OptionSide.PE
            }
            valid_expiries = sorted(
                value
                for value in ce_expiries & pe_expiries
                if value >= evaluated_at.date()
            )
            if not valid_expiries:
                return self._report(
                    **common,
                    status=MarketDataReadinessStatus.CHAIN_UNAVAILABLE,
                    reason="NO_NON_EXPIRED_COMMON_EXPIRY",
                )
            expiry = valid_expiries[0]
            expiry_items = tuple(
                item for item in instruments if item.expiry == expiry
            )
            grouped: dict[tuple[OptionSide, float], list] = defaultdict(list)
            for item in expiry_items:
                grouped[(item.option_side, float(item.strike))].append(item)
            if any(len(items) > 1 for items in grouped.values()):
                raise PaperMarketDataCorruptionError("duplicate option cell")

            ce_strikes = {
                strike for side, strike in grouped if side is OptionSide.CE
            }
            pe_strikes = {
                strike for side, strike in grouped if side is OptionSide.PE
            }
            common_strikes = tuple(sorted(ce_strikes & pe_strikes))
            interval = _dominant_interval(common_strikes)
            atm = _nearest_atm(common_strikes, spot_quote.last_price)
            target_strikes = tuple(
                atm + interval * offset for offset in range(-4, 5)
            )
            target_set = {round(value, 8) for value in target_strikes}
            window_common = {
                round(value, 8)
                for value in common_strikes
                if target_strikes[0] <= value <= target_strikes[-1]
            }
            if window_common - target_set:
                raise PaperMarketDataCorruptionError("irregular target window")
            if target_set - window_common:
                return self._report(
                    **common,
                    status=MarketDataReadinessStatus.CHAIN_COVERAGE_INCOMPLETE,
                    reason="CHAIN_COVERAGE_INCOMPLETE",
                    expiry=expiry,
                    interval=interval,
                    atm=atm,
                )

            selected = []
            seen_keys: set[str] = set()
            for offset, strike in zip(range(-4, 5), target_strikes):
                for side in (OptionSide.CE, OptionSide.PE):
                    cell = grouped.get((side, float(strike)), [])
                    if not cell:
                        return self._report(
                            **common,
                            status=MarketDataReadinessStatus.CHAIN_COVERAGE_INCOMPLETE,
                            reason="CHAIN_COVERAGE_INCOMPLETE",
                            expiry=expiry,
                            interval=interval,
                            atm=atm,
                        )
                    if len(cell) != 1:
                        raise PaperMarketDataCorruptionError("ambiguous option cell")
                    item = cell[0]
                    if item.instrument_key in seen_keys:
                        raise PaperMarketDataCorruptionError("duplicate identity")
                    seen_keys.add(item.instrument_key)
                    selected.append((item, offset))

            quotes = self.market_data.quotes(
                instrument_keys=tuple(
                    item.instrument_key for item, _ in selected
                ),
                evaluated_at=evaluated_at,
            )
            quote_map = {quote.instrument_key: quote for quote in quotes}
            if len(quote_map) != len(quotes):
                raise PaperMarketDataCorruptionError("duplicate quote identity")
            requested = {item.instrument_key for item, _ in selected}
            if any(key not in requested for key in quote_map):
                raise PaperMarketDataCorruptionError("unrequested quote identity")
        except PaperMarketDataAuthenticationError:
            return self._report(
                **common,
                status=MarketDataReadinessStatus.AUTHENTICATION_FAILED,
                reason="AUTHENTICATION_FAILED",
            )
        except PaperMarketDataRateLimitError:
            return self._report(
                **common,
                status=MarketDataReadinessStatus.RATE_LIMITED,
                reason="RATE_LIMITED",
            )
        except PaperMarketDataStaleError:
            return self._report(
                **common,
                status=MarketDataReadinessStatus.QUOTES_STALE,
                reason="QUOTES_STALE",
                expiry=locals().get("expiry"),
                interval=locals().get("interval"),
                atm=locals().get("atm"),
            )
        except PaperMarketDataUnavailableError:
            return self._report(
                **common,
                status=MarketDataReadinessStatus.QUOTES_UNAVAILABLE,
                reason="QUOTES_UNAVAILABLE",
                expiry=locals().get("expiry"),
                interval=locals().get("interval"),
                atm=locals().get("atm"),
            )
        except (PaperMarketDataCorruptionError, ValueError, TypeError):
            return self._report(
                **common,
                status=MarketDataReadinessStatus.DATA_CORRUPT,
                reason="DATA_CORRUPT",
            )

        evidence = []
        for item, offset in selected:
            quote = quote_map.get(item.instrument_key)
            if quote is None:
                row_status = ContractReadinessStatus.QUOTE_MISSING
                reason = "QUOTE_MISSING"
                last = bid = ask = timestamp = spread = None
            else:
                if (
                    quote.provider != self.market_data.provider_name
                    or quote.instrument_key != item.instrument_key
                ):
                    return self._report(
                        **common,
                        status=MarketDataReadinessStatus.DATA_CORRUPT,
                        reason="DATA_CORRUPT",
                        expiry=expiry,
                        interval=interval,
                        atm=atm,
                    )
                last = quote.last_price
                bid = quote.bid_price
                ask = quote.ask_price
                timestamp = quote.quote_timestamp
                try:
                    verify_timestamp_freshness(
                        timestamp=timestamp,
                        evaluated_at=evaluated_at,
                        maximum_age_seconds=self.policy.max_quote_age_seconds,
                    )
                except PaperMarketDataStaleError:
                    row_status = ContractReadinessStatus.QUOTE_STALE
                    reason = "QUOTE_STALE"
                    spread = None
                except (PaperMarketDataCorruptionError, ValueError, TypeError):
                    return self._report(
                        **common,
                        status=MarketDataReadinessStatus.DATA_CORRUPT,
                        reason="DATA_CORRUPT",
                        expiry=expiry,
                        interval=interval,
                        atm=atm,
                    )
                else:
                    if bid is None or ask is None:
                        row_status = ContractReadinessStatus.BID_ASK_MISSING
                        reason = "BID_ASK_MISSING"
                        spread = None
                    else:
                        midpoint = (bid + ask) / 2.0
                        spread = ((ask - bid) / midpoint) * 100.0
                        if spread > self.policy.maximum_spread_percentage:
                            row_status = ContractReadinessStatus.SPREAD_TOO_WIDE
                            reason = "SPREAD_TOO_WIDE"
                        else:
                            row_status = ContractReadinessStatus.READY
                            reason = "READY"
            evidence.append(
                ContractReadinessEvidence(
                    item.instrument_key,
                    item.trading_symbol,
                    item.option_side,
                    item.strike,
                    item.expiry,
                    _moneyness(item.option_side, offset),
                    offset,
                    item.lot_size,
                    last,
                    bid,
                    ask,
                    spread,
                    timestamp,
                    row_status,
                    reason,
                )
            )

        if any(
            row.status is ContractReadinessStatus.QUOTE_STALE
            for row in evidence
        ):
            status, reason = MarketDataReadinessStatus.QUOTES_STALE, "QUOTES_STALE"
        elif any(
            row.status is ContractReadinessStatus.QUOTE_MISSING
            for row in evidence
        ):
            status, reason = (
                MarketDataReadinessStatus.QUOTES_UNAVAILABLE,
                "QUOTES_UNAVAILABLE",
            )
        elif any(
            row.status in {
                ContractReadinessStatus.BID_ASK_MISSING,
                ContractReadinessStatus.SPREAD_TOO_WIDE,
            }
            for row in evidence
        ):
            status, reason = (
                MarketDataReadinessStatus.QUOTE_QUALITY_PARTIAL,
                "QUOTE_QUALITY_PARTIAL",
            )
        else:
            ready = sum(
                row.status is ContractReadinessStatus.READY
                for row in evidence
            )
            ce_coverage = sum(
                row.option_side is OptionSide.CE for row in evidence
            )
            pe_coverage = sum(
                row.option_side is OptionSide.PE for row in evidence
            )
            if (
                ready == 18
                and ce_coverage >= self.policy.min_ce_coverage
                and pe_coverage >= self.policy.min_pe_coverage
            ):
                status, reason = MarketDataReadinessStatus.READY, "READY"
            else:
                status, reason = (
                    MarketDataReadinessStatus.DATA_CORRUPT,
                    "DATA_CORRUPT",
                )
        return self._report(
            **common,
            status=status,
            reason=reason,
            expiry=expiry,
            interval=interval,
            atm=atm,
            contracts=evidence,
        )
