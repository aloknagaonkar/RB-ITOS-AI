from __future__ import annotations

from collections import Counter
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
    differences = [round(unique[index + 1] - unique[index], 8) for index in range(len(unique) - 1)]
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
    return min(set(float(value) for value in strikes), key=lambda value: (abs(value - spot), value))


def _moneyness(side: OptionSide, distance_steps: int) -> str:
    if distance_steps == 0:
        return "ATM"
    if side is OptionSide.CE:
        return "ITM" if distance_steps < 0 else "OTM"
    return "OTM" if distance_steps < 0 else "ITM"


class PaperMarketDataReadinessService:
    def __init__(self, *, market_data: PaperCanaryMarketData, policy: MarketDataReadinessPolicy, clock: Clock) -> None:
        self.market_data = market_data
        self.policy = policy
        self.clock = clock
        if policy.strike_steps != 4:
            raise ValueError("readiness strike_steps must be 4 for bounded 18-row evidence")

    def _report(self, *, evaluated_at: datetime, underlying: str, status: MarketDataReadinessStatus, reason: str, provider: str | None = None, underlying_key: str | None = None, spot: float | None = None, spot_timestamp: datetime | None = None, expiry=None, interval: float | None = None, atm: float | None = None, contracts=()) -> MarketDataReadinessReport:
        evidence = tuple(contracts)
        expected = 18 if expiry is not None and atm is not None else 0
        observed = len(evidence)
        ready = sum(item.status is ContractReadinessStatus.READY for item in evidence)
        ce = sum(item.option_side is OptionSide.CE for item in evidence)
        pe = sum(item.option_side is OptionSide.PE for item in evidence)
        provider_name = provider or self.market_data.provider_name
        return MarketDataReadinessReport(
            probe_id=build_probe_id(provider=provider_name, underlying=underlying, evaluated_at=evaluated_at, expiry=expiry, atm_strike=atm),
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
        try:
            spot_quote = self.market_data.underlying_quote(underlying=underlying, evaluated_at=evaluated_at)
            if spot_quote.provider != self.market_data.provider_name or spot_quote.underlying != underlying:
                raise PaperMarketDataCorruptionError("underlying quote identity mismatch")
            verify_timestamp_freshness(timestamp=spot_quote.quote_timestamp, evaluated_at=evaluated_at, maximum_age_seconds=self.policy.max_quote_age_seconds)
            instruments = self.market_data.option_instruments(underlying=underlying, evaluated_at=evaluated_at)
        except PaperMarketDataAuthenticationError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.AUTHENTICATION_FAILED, reason="AUTHENTICATION_FAILED")
        except PaperMarketDataRateLimitError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.RATE_LIMITED, reason="RATE_LIMITED")
        except PaperMarketDataUnavailableError as exc:
            reason = "SPOT_UNAVAILABLE" if "underlying" in str(exc).lower() or "spot" in str(exc).lower() else "PROVIDER_UNAVAILABLE"
            status = MarketDataReadinessStatus.SPOT_UNAVAILABLE if reason == "SPOT_UNAVAILABLE" else MarketDataReadinessStatus.PROVIDER_UNAVAILABLE
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=status, reason=reason)
        except (PaperMarketDataCorruptionError, ValueError, TypeError):
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.DATA_CORRUPT, reason="DATA_CORRUPT")

        if not instruments:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.CHAIN_UNAVAILABLE, reason="CHAIN_UNAVAILABLE", underlying_key=spot_quote.instrument_key, spot=spot_quote.last_price, spot_timestamp=spot_quote.quote_timestamp)

        try:
            expiries_ce = {item.expiry for item in instruments if item.option_side is OptionSide.CE}
            expiries_pe = {item.expiry for item in instruments if item.option_side is OptionSide.PE}
            common_expiries = sorted(expiries_ce & expiries_pe)
            if not common_expiries:
                raise PaperMarketDataCorruptionError("common expiry unavailable")
            expiry = common_expiries[0]
            expiry_items = tuple(item for item in instruments if item.expiry == expiry)
            strikes = tuple(item.strike for item in expiry_items)
            interval = _dominant_interval(strikes)
            common_strikes = tuple(sorted({item.strike for item in expiry_items if item.option_side is OptionSide.CE} & {item.strike for item in expiry_items if item.option_side is OptionSide.PE}))
            atm = _nearest_atm(common_strikes, spot_quote.last_price)
            target_strikes = tuple(atm + interval * offset for offset in range(-4, 5))
            by_cell = {(item.option_side, float(item.strike)): item for item in expiry_items}
            expected_cells = tuple((side, strike, offset) for offset, strike in zip(range(-4, 5), target_strikes) for side in (OptionSide.CE, OptionSide.PE))
            selected = []
            seen_keys: set[str] = set()
            for side, strike, offset in expected_cells:
                matches = [item for (cell_side, cell_strike), item in by_cell.items() if cell_side is side and isclose(cell_strike, strike, abs_tol=1e-8)]
                if len(matches) != 1:
                    return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.CHAIN_COVERAGE_INCOMPLETE, reason="CHAIN_COVERAGE_INCOMPLETE", underlying_key=spot_quote.instrument_key, spot=spot_quote.last_price, spot_timestamp=spot_quote.quote_timestamp, expiry=expiry, interval=interval, atm=atm)
                item = matches[0]
                if item.instrument_key in seen_keys:
                    raise PaperMarketDataCorruptionError("duplicate option identity")
                seen_keys.add(item.instrument_key); selected.append((item, offset))
            quotes = self.market_data.quotes(instrument_keys=tuple(item.instrument_key for item, _ in selected), evaluated_at=evaluated_at)
            quote_map = {quote.instrument_key: quote for quote in quotes}
            if len(quote_map) != len(quotes):
                raise PaperMarketDataCorruptionError("duplicate quote identity")
        except PaperMarketDataAuthenticationError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.AUTHENTICATION_FAILED, reason="AUTHENTICATION_FAILED")
        except PaperMarketDataRateLimitError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.RATE_LIMITED, reason="RATE_LIMITED")
        except PaperMarketDataUnavailableError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.QUOTES_STALE, reason="QUOTES_STALE", underlying_key=spot_quote.instrument_key, spot=spot_quote.last_price, spot_timestamp=spot_quote.quote_timestamp, expiry=locals().get("expiry"), interval=locals().get("interval"), atm=locals().get("atm"))
        except (PaperMarketDataCorruptionError, ValueError, TypeError):
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.DATA_CORRUPT, reason="DATA_CORRUPT", underlying_key=spot_quote.instrument_key, spot=spot_quote.last_price, spot_timestamp=spot_quote.quote_timestamp)

        evidence = []
        for item, offset in selected:
            quote = quote_map.get(item.instrument_key)
            if quote is None:
                status = ContractReadinessStatus.QUOTE_MISSING; reason = "QUOTE_MISSING"; spread = None
                last = bid = ask = timestamp = None
            else:
                if quote.provider != self.market_data.provider_name:
                    raise PaperMarketDataCorruptionError("quote provider mismatch")
                last, bid, ask, timestamp = quote.last_price, quote.bid_price, quote.ask_price, quote.quote_timestamp
                if bid is None or ask is None:
                    status = ContractReadinessStatus.BID_ASK_MISSING; reason = "BID_ASK_MISSING"; spread = None
                else:
                    midpoint = (bid + ask) / 2.0; spread = ((ask - bid) / midpoint) * 100.0
                    if spread > self.policy.maximum_spread_percentage:
                        status = ContractReadinessStatus.SPREAD_TOO_WIDE; reason = "SPREAD_TOO_WIDE"
                    else:
                        status = ContractReadinessStatus.READY; reason = "READY"
            evidence.append(ContractReadinessEvidence(item.instrument_key, item.trading_symbol, item.option_side, item.strike, item.expiry, _moneyness(item.option_side, offset), offset, item.lot_size, last, bid, ask, spread, timestamp, status, reason))

        ready = sum(row.status is ContractReadinessStatus.READY for row in evidence)
        missing = any(row.status is ContractReadinessStatus.QUOTE_MISSING for row in evidence)
        partial = any(row.status in {ContractReadinessStatus.BID_ASK_MISSING, ContractReadinessStatus.SPREAD_TOO_WIDE} for row in evidence)
        if missing:
            overall, reason = MarketDataReadinessStatus.QUOTES_UNAVAILABLE, "QUOTES_UNAVAILABLE"
        elif partial:
            overall, reason = MarketDataReadinessStatus.QUOTE_QUALITY_PARTIAL, "QUOTE_QUALITY_PARTIAL"
        elif ready == 18:
            overall, reason = MarketDataReadinessStatus.READY, "READY"
        else:
            overall, reason = MarketDataReadinessStatus.DATA_CORRUPT, "DATA_CORRUPT"
        return self._report(evaluated_at=evaluated_at, underlying=underlying, status=overall, reason=reason, underlying_key=spot_quote.instrument_key, spot=spot_quote.last_price, spot_timestamp=spot_quote.quote_timestamp, expiry=expiry, interval=interval, atm=atm, contracts=evidence)
