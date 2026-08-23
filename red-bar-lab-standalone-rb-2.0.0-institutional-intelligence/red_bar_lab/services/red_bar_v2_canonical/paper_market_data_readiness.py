from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import isclose
from typing import Protocol

from red_bar_lab.domain.red_bar_v2 import OptionSide

from .paper_market_data import (
    PaperCanaryMarketData,
    PaperMarketDataAuthenticationError,
    PaperMarketDataCorruptionError,
    PaperMarketDataRateLimitError,
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
    if len(modes) != 1:
        raise PaperMarketDataCorruptionError("ambiguous strike interval")
    interval = modes[0]
    if highest < 2:
        raise PaperMarketDataCorruptionError("irregular strike interval")
    return interval


def _nearest_atm(strikes: tuple[float, ...], spot: float) -> float:
    if not strikes:
        raise PaperMarketDataCorruptionError("ATM strike unavailable")
    # Deterministic halfway rule: lower strike wins.
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
            raise ValueError(
                "readiness strike_steps must be 4 for bounded 18-row evidence"
            )
        if policy.min_ce_coverage != 9 or policy.min_pe_coverage != 9:
            raise ValueError(
                "readiness CE and PE coverage must each be exactly 9"
            )

    def _report(
        self,
        *,
        evaluated_at: datetime,
        underlying: str,
        status: MarketDataReadinessStatus,
        reason: str,
        provider: str | None = None,
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
        observed = len(evidence)
        ready = sum(
            item.status is ContractReadinessStatus.READY for item in evidence
        )
        ce = sum(item.option_side is OptionSide.CE for item in evidence)
        pe = sum(item.option_side is OptionSide.PE for item in evidence)
        provider_name = provider or self.market_data.provider_name
        return MarketDataReadinessReport(
            probe_id=build_probe_id(
                provider=provider_name,
                underlying=underlying,
                evaluated_at=evaluated_at,
                expiry=expiry,
                atm_strike=atm,
            ),
            provider=provider_name,
            underlying=underlying,
            underlying_instrument_key=underlying_key,
            evaluated_at=evaluated_at,
            spot_price=spot,
            spot_timestamp=spot_timestamp,
            expiry=expiry,
            strike_interval=interval,
            atm_strike=atm,
            expected_contract_count=expected,
            observed_contract_count=observed,
            ready_contract_count=ready,
            ce_coverage=ce,
            pe_coverage=pe,
            status=status,
            reason_code=reason,
            contracts=evidence,
        )

    def evaluate(self, *, underlying: str) -> MarketDataReadinessReport:
        evaluated_at = self.clock.now()
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("readiness clock must be timezone-aware")

        # Spot acquisition and classification are deliberately isolated from
        # option-chain acquisition; no exception-message inspection is used.
        try:
            spot_quote = self.market_data.underlying_quote(
                underlying=underlying,
                evaluated_at=evaluated_at,
            )
            if (
                spot_quote.provider != self.market_data.provider_name
                or spot_quote.underlying != underlying
            ):
                raise PaperMarketDataCorruptionError(
                    "underlying quote identity mismatch"
                )
            verify_timestamp_freshness(
                timestamp=spot_quote.quote_timestamp,
                evaluated_at=evaluated_at,
                maximum_age_seconds=self.policy.max_quote_age_seconds,
            )
        except PaperMarketDataAuthenticationError:
            return self._report(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.AUTHENTICATION_FAILED,
                reason="AUTHENTICATION_FAILED",
            )
        except PaperMarketDataRateLimitError:
            return self._report(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.RATE_LIMITED,
                reason="RATE_LIMITED",
            )
        except PaperMarketDataUnavailableError:
            return self._report(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.SPOT_UNAVAILABLE,
                reason="SPOT_UNAVAILABLE",
            )
        except (PaperMarketDataCorruptionError, ValueError, TypeError):
            return self._report(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.DATA_CORRUPT,
                reason="DATA_CORRUPT",
            )

        try:
            instruments = self.market_data.option_instruments(
                underlying=underlying,
                evaluated_at=evaluated_at,
            )
        except PaperMarketDataAuthenticationError:
            return self._report(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.AUTHENTICATION_FAILED,
                reason="AUTHENTICATION_FAILED",
            )
        except PaperMarketDataRateLimitError:
            return self._report(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.RATE_LIMITED,
                reason="RATE_LIMITED",
            )
        except PaperMarketDataUnavailableError:
            return self._report(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.PROVIDER_UNAVAILABLE,
                reason="PROVIDER_UNAVAILABLE",
                underlying_key=spot_quote.instrument_key,
                spot=spot_quote.last_price,
                spot_timestamp=spot_quote.quote_timestamp,
            )
        except (PaperMarketDataCorruptionError, ValueError, TypeError):
            return self._report(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.DATA_CORRUPT,
                reason="DATA_CORRUPT",
                underlying_key=spot_quote.instrument_key,
                spot=spot_quote.last_price,
                spot_timestamp=spot_quote.quote_timestamp,
            )

        if not instruments:
            return self._report(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.CHAIN_UNAVAILABLE,
                reason="CHAIN_UNAVAILABLE",
                underlying_key=spot_quote.instrument_key,
                spot=spot_quote.last_price,
                spot_timestamp=spot_quote.quote_timestamp,
            )

        try:
            expiries_ce = {
                item.expiry
                for item in instruments
                if item.option_side is OptionSide.CE
            }
            expiries_pe = {
                item.expiry
                for item in instruments
                if item.option_side is OptionSide.PE
            }
            valid_common_expiries = sorted(
                expiry
                for expiry in expiries_ce & expiries_pe
                if expiry >= evaluated_at.date()
            )
            if not valid_common_expiries:
                return self._report(
                    evaluated_at=evaluated_at,
                    underlying=underlying,
                    status=MarketDataReadinessStatus.CHAIN_UNAVAILABLE,
                    reason="NO_NON_EXPIRED_COMMON_EXPIRY",
                    underlying_key=spot_quote.instrument_key,
                    spot=spot_quote.last_price,
                    spot_timestamp=spot_quote.quote_timestamp,
                )
            expiry = valid_common_expiries[0]
            expiry_items = tuple(
                item for item in instruments if item.expiry == expiry
            )

            grouped_cells: dict[tuple[OptionSide, float], list] = defaultdict(list)
            for item in expiry_items:
                grouped_cells[(item.option_side, float(item.strike))].append(item)
            if any(len(items) > 1 for items in grouped_cells.values()):
                raise PaperMarketDataCorruptionError(
                    "duplicate option contracts occupy one readiness cell"
                )

            common_strikes = tuple(
                sorted(
                    {
                        strike
                        for side, strike in grouped_cells
                        if side is OptionSide.CE
                    }
                    & {
                        strike
                        for side, strike in grouped_cells
                        if side is OptionSide.PE
                    }
                )
            )
            interval = _dominant_interval(common_strikes)
            atm = _nearest_atm(common_strikes, spot_quote.last_price)
            target_strikes = tuple(
                atm + interval * offset for offset in range(-4, 5)
            )

            # The detected interval must be regular throughout the exact target
            # window. Missing target strikes are incomplete coverage; additional
            # irregular common strikes inside the bounded window are corruption.
            target_set = {round(value, 8) for value in target_strikes}
            common_in_window = {
                round(value, 8)
                for value in common_strikes
                if target_strikes[0] <= value <= target_strikes[-1]
            }
            missing_target_strikes = target_set - common_in_window
            extra_window_strikes = common_in_window - target_set
            if extra_window_strikes:
                raise PaperMarketDataCorruptionError(
                    "irregular strike interval inside readiness window"
                )
            if missing_target_strikes:
                return self._report(
                    evaluated_at=evaluated_at,
                    underlying=underlying,
                    status=(
                        MarketDataReadinessStatus.CHAIN_COVERAGE_INCOMPLETE
                    ),
                    reason="CHAIN_COVERAGE_INCOMPLETE",
                    underlying_key=spot_quote.instrument_key,
                    spot=spot_quote.last_price,
                    spot_timestamp=spot_quote.quote_timestamp,
                    expiry=expiry,
                    interval=interval,
                    atm=atm,
                )

            expected_cells = tuple(
                (side, strike, offset)
                for offset, strike in zip(range(-4, 5), target_strikes)
                for side in (OptionSide.CE, OptionSide.PE)
            )
            selected = []
            seen_keys: set[str] = set()
            for side, strike, offset in expected_cells:
                cell_items = grouped_cells.get((side, float(strike)), [])
                if not cell_items:
                    return self._report(
                        evaluated_at=evaluated_at,
                        underlying=underlying,
                        status=(
                            MarketDataReadinessStatus.CHAIN_COVERAGE_INCOMPLETE
                        ),
                        reason="CHAIN_COVERAGE_INCOMPLETE",
                        underlying_key=spot_quote.instrument_key,
                        spot=spot_quote.last_price,
                        spot_timestamp=spot_quote.quote_timestamp,
                        expiry=expiry,
                        interval=interval,
                        atm=atm,
                    )
                if len(cell_items) != 1:
                    raise PaperMarketDataCorruptionError(
                        "ambiguous readiness contract cell"
                    )
                item = cell_items[0]
                if item.instrument_key in seen_keys:
                    raise PaperMarketDataCorruptionError(
                        "duplicate option identity"
                    )
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
            requested_keys = {item.instrument_key for item, _ in selected}
            if any(key not in requested_keys for key in quote_map):
                raise PaperMarketDataCorruptionError(
                    "unrequested quote identity"
                )
        except PaperMarketDataAuthenticationError:
            return self._report(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.AUTHENTICATION_FAILED,
                reason="AUTHENTICATION_FAILED",
            )
        except PaperMarketDataRateLimitError:
            return self._report(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.RATE_LIMITED,
                reason="RATE_LIMITED",
            )
        except PaperMarketDataUnavailableError:
            return self._report(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.QUOTES_UNAVAILABLE,
                reason="QUOTES_UNAVAILABLE",
                underlying_key=spot_quote.instrument_key,
                spot=spot_quote.last_price,
                spot_timestamp=spot_quote.quote_timestamp,
                expiry=locals().get("expiry"),
                interval=locals().get("interval"),
                atm=locals().get("atm"),
            )
        except (PaperMarketDataCorruptionError, ValueError, TypeError):
            return self._report(
                evaluated_at=evaluated_at,
                underlying=underlying,
                status=MarketDataReadinessStatus.DATA_CORRUPT,
                reason="DATA_CORRUPT",
                underlying_key=spot_quote.instrument_key,
                spot=spot_quote.last_price,
                spot_timestamp=spot_quote.quote_timestamp,
            )

        evidence = []
        for item, offset in selected:
            quote = quote_map.get(item.instrument_key)
            if quote is None:
                status = ContractReadinessStatus.QUOTE_MISSING
                reason = "QUOTE_MISSING"
                spread = None
                last = bid = ask = timestamp = None
            else:
                if (
                    quote.provider != self.market_data.provider_name
                    or quote.instrument_key != item.instrument_key
                ):
                    return self._report(
                        evaluated_at=evaluated_at,
                        underlying=underlying,
                        status=MarketDataReadinessStatus.DATA_CORRUPT,
                        reason="DATA_CORRUPT",
                        underlying_key=spot_quote.instrument_key,
                        spot=spot_quote.last_price,
                        spot_timestamp=spot_quote.quote_timestamp,
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
                        maximum_age_seconds=(
                            self.policy.max_quote_age_seconds
                        ),
                    )
                except PaperMarketDataUnavailableError:
                    status = ContractReadinessStatus.QUOTE_STALE
                    reason = "QUOTE_STALE"
                    spread = None
                except (PaperMarketDataCorruptionError, ValueError, TypeError):
                    return self._report(
                        evaluated_at=evaluated_at,
                        underlying=underlying,
                        status=MarketDataReadinessStatus.DATA_CORRUPT,
                        reason="DATA_CORRUPT",
                        underlying_key=spot_quote.instrument_key,
                        spot=spot_quote.last_price,
                        spot_timestamp=spot_quote.quote_timestamp,
                        expiry=expiry,
                        interval=interval,
                        atm=atm,
                    )
                else:
                    if bid is None or ask is None:
                        status = ContractReadinessStatus.BID_ASK_MISSING
                        reason = "BID_ASK_MISSING"
                        spread = None
                    else:
                        midpoint = (bid + ask) / 2.0
                        spread = ((ask - bid) / midpoint) * 100.0
                        if spread > self.policy.maximum_spread_percentage:
                            status = ContractReadinessStatus.SPREAD_TOO_WIDE
                            reason = "SPREAD_TOO_WIDE"
                        else:
                            status = ContractReadinessStatus.READY
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
                    status,
                    reason,
                )
            )

        ready = sum(
            row.status is ContractReadinessStatus.READY for row in evidence
        )
        stale = any(
            row.status is ContractReadinessStatus.QUOTE_STALE
            for row in evidence
        )
        missing = any(
            row.status is ContractReadinessStatus.QUOTE_MISSING
            for row in evidence
        )
        partial = any(
            row.status
            in {
                ContractReadinessStatus.BID_ASK_MISSING,
                ContractReadinessStatus.SPREAD_TOO_WIDE,
            }
            for row in evidence
        )
        ce_coverage = sum(
            row.option_side is OptionSide.CE for row in evidence
        )
        pe_coverage = sum(
            row.option_side is OptionSide.PE for row in evidence
        )
        if stale:
            overall, reason = (
                MarketDataReadinessStatus.QUOTES_STALE,
                "QUOTES_STALE",
            )
        elif missing:
            overall, reason = (
                MarketDataReadinessStatus.QUOTES_UNAVAILABLE,
                "QUOTES_UNAVAILABLE",
            )
        elif partial:
            overall, reason = (
                MarketDataReadinessStatus.QUOTE_QUALITY_PARTIAL,
                "QUOTE_QUALITY_PARTIAL",
            )
        elif (
            ready == 18
            and ce_coverage >= self.policy.min_ce_coverage
            and pe_coverage >= self.policy.min_pe_coverage
        ):
            overall, reason = MarketDataReadinessStatus.READY, "READY"
        else:
            overall, reason = (
                MarketDataReadinessStatus.DATA_CORRUPT,
                "DATA_CORRUPT",
            )
        return self._report(
            evaluated_at=evaluated_at,
            underlying=underlying,
            status=overall,
            reason=reason,
            underlying_key=spot_quote.instrument_key,
            spot=spot_quote.last_price,
            spot_timestamp=spot_quote.quote_timestamp,
            expiry=expiry,
            interval=interval,
            atm=atm,
            contracts=evidence,
        )
