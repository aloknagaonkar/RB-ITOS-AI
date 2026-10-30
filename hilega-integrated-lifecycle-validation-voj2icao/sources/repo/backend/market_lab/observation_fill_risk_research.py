"""Hypothetical option fill and capital-risk research; never creates orders."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import floor, isfinite
from typing import Iterable


@dataclass(frozen=True)
class RiskBudget:
    capital: float
    cash_risk_fraction: float
    daily_loss_fraction: float
    premium_exposure_fraction: float
    combined_exposure_fraction: float
    current_daily_loss: float = 0.0
    existing_premium_exposure: float = 0.0


@dataclass(frozen=True)
class OptionQuoteScenario:
    entry_ask: float
    exit_bid: float
    protective_exit_bid: float
    gap_exit_bid: float
    multiplier: int
    entry_slippage: float
    exit_slippage: float
    round_trip_charges_per_contract: float
    latency_seconds: float = 0.0
    fill_fraction: float = 1.0


def _finite_positive(value: float, name: str, *, zero: bool = False) -> None:
    if not isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f"{name} must be finite and {'nonnegative' if zero else 'positive'}")


def project_option_scenario(budget: RiskBudget, quote: OptionQuoteScenario) -> dict:
    """Conservative per-contract costs and an informational maximum lot count.

    Missing executable quotes must be represented by no scenario, rather than
    substituting observed OHLC. This result cannot authorize execution.
    """
    _finite_positive(budget.capital, "capital")
    for name in ("cash_risk_fraction", "daily_loss_fraction", "premium_exposure_fraction", "combined_exposure_fraction"):
        value = getattr(budget, name)
        _finite_positive(value, name, zero=True)
        if value > 1:
            raise ValueError(f"{name} must be <= 1")
    for name in ("current_daily_loss", "existing_premium_exposure"):
        _finite_positive(getattr(budget, name), name, zero=True)
    for name in ("entry_ask", "exit_bid", "protective_exit_bid", "gap_exit_bid"):
        _finite_positive(getattr(quote, name), name, zero=True)
    for name in ("entry_slippage", "exit_slippage", "round_trip_charges_per_contract", "latency_seconds"):
        _finite_positive(getattr(quote, name), name, zero=True)
    if not isinstance(quote.multiplier, int) or quote.multiplier <= 0:
        raise ValueError("multiplier must be a positive integer")
    if not 0 <= quote.fill_fraction <= 1 or not isfinite(quote.fill_fraction):
        raise ValueError("fill_fraction must be finite within [0,1]")
    entry = quote.entry_ask + quote.entry_slippage
    exit_ = max(0.0, quote.exit_bid - quote.exit_slippage)
    worst_exit = max(0.0, min(quote.protective_exit_bid, quote.gap_exit_bid) - quote.exit_slippage)
    premium = entry * quote.multiplier
    net_per_contract = (exit_ - entry) * quote.multiplier - quote.round_trip_charges_per_contract
    worst_loss = max(0.0, entry - worst_exit) * quote.multiplier + quote.round_trip_charges_per_contract
    max_cash_loss = premium + quote.round_trip_charges_per_contract
    cash_risk_left = budget.capital * budget.cash_risk_fraction
    daily_left = max(0.0, budget.capital * budget.daily_loss_fraction - budget.current_daily_loss)
    exposure_left = max(0.0, budget.capital * min(budget.premium_exposure_fraction,
                    budget.combined_exposure_fraction) - budget.existing_premium_exposure)
    lots = max(0, floor(min(cash_risk_left / max_cash_loss, daily_left / max_cash_loss,
                            exposure_left / premium)))
    return {
        "mode": "OBSERVATION_ONLY_RESEARCH", "order_created": False, "quantity": None,
        "entry_cost_per_contract": round(premium, 2),
        "net_mark_to_exit_per_contract": round(net_per_contract, 2),
        "gap_adjusted_worst_loss_per_contract": round(worst_loss, 2),
        "maximum_premium_loss_per_contract": round(max_cash_loss, 2),
        "informational_max_lots": lots if quote.fill_fraction == 1 else 0,
        "partial_fill_fraction": quote.fill_fraction,
        "latency_seconds_assumed": quote.latency_seconds,
        "blocked_reason": "PARTIAL_OR_REJECTED_FILL" if quote.fill_fraction < 1 else
                          "BUDGET_EXHAUSTED" if lots == 0 else None,
        "inputs": {"budget": asdict(budget), "quote": asdict(quote)},
    }


def capital_weighted_equity(capital: float, marked_positions: Iterable[tuple[str, float]]) -> dict:
    """Chronological account P&L marks in cash, including open positions."""
    _finite_positive(capital, "capital")
    equity = capital
    peak = capital
    curve = []
    last_time = None
    for timestamp, cash_delta in marked_positions:
        _finite_positive(abs(cash_delta), "cash_delta", zero=True)
        if last_time is not None and timestamp <= last_time:
            raise ValueError("equity marks must be strictly chronological")
        last_time = timestamp
        equity += cash_delta
        peak = max(peak, equity)
        curve.append({"timestamp": timestamp, "equity": round(equity, 2),
                      "drawdown_fraction": (peak - equity) / peak})
    return {"initial_capital": capital, "latest_equity": round(equity, 2),
            "max_drawdown_fraction": max((x["drawdown_fraction"] for x in curve), default=0.0),
            "curve": curve}
