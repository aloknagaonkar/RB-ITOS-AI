from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from statistics import median
from typing import Iterable

from .historical_option_intrabar_replay_v1 import replay_intrabar_date
from .historical_option_ohlc_adapter_v1 import discover_option_ohlc_files
from .historical_positioning_adapter_v1 import discover_positioning_sessions

CANONICAL_START = date(2026, 5, 4)
CANONICAL_END = date(2026, 9, 8)
EXPECTED_CANONICAL_SESSIONS = 90

ALLOWED_BUCKET_SUFFIXES = {
    "train",
    "oos-a",
    "oos-b",
    "oos-c",
    "oos-d",
}

DEFAULT_FUTURES_CSV = Path(
    "data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv"
)


class CanonicalReplayError(RuntimeError):
    pass


@dataclass(frozen=True)
class SessionReplayRow:
    session_date: str
    status: str
    signals: int = 0
    entries: int = 0
    entry_rejects: int = 0
    closed: int = 0
    winners: int = 0
    losers: int = 0
    breakeven: int = 0
    aggregate_pnl_pct: float = 0.0
    bullish_trades: int = 0
    bearish_trades: int = 0
    hard_stop: int = 0
    breakeven_stop: int = 0
    trail_stop: int = 0
    open_at_end: int = 0
    error: str | None = None


@dataclass
class CanonicalReplayReport:
    universe_dates: list[str]
    session_rows: list[SessionReplayRow] = field(default_factory=list)
    trade_returns_pct: list[float] = field(default_factory=list)
    trade_directions: list[str] = field(default_factory=list)
    trade_exit_reasons: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        passed = [r for r in self.session_rows if r.status == "PASS"]
        failed = [r for r in self.session_rows if r.status != "PASS"]

        wins = sum(r.winners for r in passed)
        losses = sum(r.losers for r in passed)
        breakeven = sum(r.breakeven for r in passed)
        closed = sum(r.closed for r in passed)

        non_be = wins + losses
        win_rate_non_be = (wins / non_be * 100.0) if non_be else None
        win_rate_all_closed = (wins / closed * 100.0) if closed else None

        bullish_returns = [
            ret for ret, direction in zip(
                self.trade_returns_pct,
                self.trade_directions,
            )
            if direction == "BULLISH"
        ]
        bearish_returns = [
            ret for ret, direction in zip(
                self.trade_returns_pct,
                self.trade_directions,
            )
            if direction == "BEARISH"
        ]

        return {
            "universe_expected_sessions": EXPECTED_CANONICAL_SESSIONS,
            "universe_discovered_sessions": len(self.universe_dates),
            "sessions_passed": len(passed),
            "sessions_failed": len(failed),
            "signals": sum(r.signals for r in passed),
            "entries": sum(r.entries for r in passed),
            "entry_rejects": sum(r.entry_rejects for r in passed),
            "closed": closed,
            "open_at_end": sum(r.open_at_end for r in passed),
            "winners": wins,
            "losers": losses,
            "breakeven": breakeven,
            "win_rate_non_breakeven_pct": win_rate_non_be,
            "win_rate_all_closed_pct": win_rate_all_closed,
            "median_trade_return_pct": (
                median(self.trade_returns_pct)
                if self.trade_returns_pct
                else None
            ),
            "aggregate_trade_return_pct": sum(self.trade_returns_pct),
            "max_sequential_trade_drawdown_pct": _max_drawdown_sum_returns(
                self.trade_returns_pct
            ),
            "bullish_trades": len(bullish_returns),
            "bullish_median_return_pct": (
                median(bullish_returns) if bullish_returns else None
            ),
            "bearish_trades": len(bearish_returns),
            "bearish_median_return_pct": (
                median(bearish_returns) if bearish_returns else None
            ),
            "exit_reason_counts": {
                "HARD_STOP": self.trade_exit_reasons.count("HARD_STOP"),
                "BREAKEVEN_STOP": self.trade_exit_reasons.count("BREAKEVEN_STOP"),
                "TRAIL_STOP": self.trade_exit_reasons.count("TRAIL_STOP"),
            },
        }


def _max_drawdown_sum_returns(returns: list[float]) -> float:
    """
    Research diagnostic only.

    Treats each trade return percentage as one additive unit and measures the
    largest peak-to-trough decline in cumulative percentage points. This is NOT
    capital-weighted portfolio drawdown because quantity/capital allocation is
    not yet modeled.
    """
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def _bucket_allowed(path: Path) -> bool:
    parent = path.parent.name.lower()
    return any(
        parent == f"historical-positioning-cache-{suffix}"
        for suffix in ALLOWED_BUCKET_SUFFIXES
    )


def _read_json_date(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    if payload.get("status") != "AVAILABLE":
        return None
    value = payload.get("session_date")
    return str(value) if value else None


def _futures_dates(csv_path: str | Path) -> set[str]:
    path = Path(csv_path)
    if not path.exists():
        raise CanonicalReplayError(f"Futures CSV not found: {path}")

    dates: set[str] = set()
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            value = row.get("session_date")
            if value:
                dates.add(value)
    return dates


def discover_canonical_90_dates(
    *,
    data_root: str | Path = "data",
    futures_csv: str | Path = DEFAULT_FUTURES_CSV,
    require_exact_90: bool = True,
) -> list[str]:
    root = Path(data_root)

    positioning_dates: set[str] = set()
    for directory in sorted(root.glob("historical-positioning-cache-*")):
        if directory.name.lower().replace("historical-positioning-cache-", "") not in ALLOWED_BUCKET_SUFFIXES:
            continue
        for path in directory.glob("*.json"):
            value = _read_json_date(path)
            if value:
                positioning_dates.add(value)

    ohlc_dates: set[str] = set()
    for directory in sorted(root.glob("historical-option-ohlc-cache-*")):
        suffix = directory.name.lower().replace("historical-option-ohlc-cache-", "")
        if suffix not in ALLOWED_BUCKET_SUFFIXES:
            continue
        for path in directory.glob("*.json"):
            value = _read_json_date(path)
            if value:
                ohlc_dates.add(value)

    futures_dates = _futures_dates(futures_csv)

    dates = sorted(
        value
        for value in positioning_dates & ohlc_dates & futures_dates
        if CANONICAL_START <= date.fromisoformat(value) <= CANONICAL_END
    )

    if require_exact_90 and len(dates) != EXPECTED_CANONICAL_SESSIONS:
        raise CanonicalReplayError(
            "Canonical universe safety check failed: "
            f"expected {EXPECTED_CANONICAL_SESSIONS} sessions from "
            "TRAIN+OOS_A/B/C/D within "
            f"{CANONICAL_START}..{CANONICAL_END}, discovered {len(dates)}. "
            "Do not silently substitute another population."
        )

    return dates


def run_canonical_replay(
    *,
    data_root: str | Path = "data",
    futures_csv: str | Path = DEFAULT_FUTURES_CSV,
    require_exact_90: bool = True,
) -> CanonicalReplayReport:
    dates = discover_canonical_90_dates(
        data_root=data_root,
        futures_csv=futures_csv,
        require_exact_90=require_exact_90,
    )

    report = CanonicalReplayReport(universe_dates=dates)

    for session_date in dates:
        try:
            result = replay_intrabar_date(
                session_date,
                data_root=data_root,
                futures_csv=futures_csv,
            )

            winners = 0
            losers = 0
            breakeven = 0
            bullish = 0
            bearish = 0
            hard = 0
            be = 0
            trail = 0

            for trade in result.trades:
                if trade.entry_status != "FILLED":
                    continue

                if trade.direction == "BULLISH":
                    bullish += 1
                elif trade.direction == "BEARISH":
                    bearish += 1

                if trade.exit_time is None or trade.pnl_pct is None:
                    continue

                ret = float(trade.pnl_pct)
                report.trade_returns_pct.append(ret)
                report.trade_directions.append(trade.direction)

                if abs(ret) < 1e-12:
                    breakeven += 1
                elif ret > 0:
                    winners += 1
                else:
                    losers += 1

                reason = trade.exit_reason or "UNKNOWN"
                report.trade_exit_reasons.append(reason)
                if reason == "HARD_STOP":
                    hard += 1
                elif reason == "BREAKEVEN_STOP":
                    be += 1
                elif reason == "TRAIL_STOP":
                    trail += 1

            summary = result.summary()
            report.session_rows.append(
                SessionReplayRow(
                    session_date=session_date,
                    status="PASS",
                    signals=int(summary["signals"]),
                    entries=int(summary["entries"]),
                    entry_rejects=int(summary["entry_rejects"]),
                    closed=int(summary["closed"]),
                    winners=winners,
                    losers=losers,
                    breakeven=breakeven,
                    aggregate_pnl_pct=float(summary["aggregate_pnl_pct"]),
                    bullish_trades=bullish,
                    bearish_trades=bearish,
                    hard_stop=hard,
                    breakeven_stop=be,
                    trail_stop=trail,
                    open_at_end=int(summary["open_at_end"]),
                )
            )
        except Exception as exc:
            report.session_rows.append(
                SessionReplayRow(
                    session_date=session_date,
                    status="FAIL",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    return report
