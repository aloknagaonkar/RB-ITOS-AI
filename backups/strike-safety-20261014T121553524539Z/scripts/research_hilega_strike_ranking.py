"""Offline, observation-only ATM +/- 2 option comparison for alignment replay trades.

Reads previously published HILEGA_V2_ALIGNMENT_DUAL_EXIT replay JSON and exact
historical option OHLC caches. Never fetches quotes or creates an order. A
minute OPEN is a research proxy, not a broker fill or executable bid/ask.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from market_lab.historical_option_ohlc_adapter_v1 import choose_option_ohlc_session


ROLES = (-2, -1, 0, 1, 2)
STRATEGY = "HILEGA_V2_ALIGNMENT_DUAL_EXIT"
REPLAY_MODEL = "HILEGA_V2_ALIGNMENT_DUAL_EXIT_REPLAY_V1"


def minute(value: str, lag: int) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("STRATEGY_TIMESTAMP_MUST_HAVE_TIMEZONE")
    return stamp.replace(second=0, microsecond=0) + timedelta(minutes=lag + int(bool(stamp.second or stamp.microsecond)))


def compare_trade(trade: dict, session, *, lag_minutes: int, trade_index: int) -> list[dict]:
    direction = trade["direction"]
    if direction not in {"BULLISH", "BEARISH"}:
        raise ValueError("UNKNOWN_DIRECTION")
    side = "CE" if direction == "BULLISH" else "PE"
    entry_at = minute(trade["entry_time"], lag_minutes)
    exit_at = minute(trade["exit_time"], lag_minutes)
    spot = float(trade["entry_price"])
    step = int(session.strike_interval)
    if step <= 0:
        raise ValueError("INVALID_STRIKE_INTERVAL")
    # The replay's accepted underlying entry price fixes ATM for all five legs.
    atm = int((spot / step) + 0.5) * step
    index: dict[tuple[str, float, str], dict[datetime, object]] = defaultdict(dict)
    identity: dict[tuple[str, float], str] = {}
    duplicates: set[tuple[str, float, str, datetime]] = set()
    for candle in session.rows:
        if candle.side != side or candle.expiry != session.expiry:
            continue
        key = (candle.side, float(candle.strike))
        old = identity.setdefault(key, candle.instrument_key)
        if old != candle.instrument_key:
            raise ValueError("AMBIGUOUS_CONTRACT_IDENTITY")
        series = index[(candle.side, float(candle.strike), candle.instrument_key)]
        if candle.timestamp in series:
            duplicates.add((*key, candle.instrument_key, candle.timestamp))
        series[candle.timestamp] = candle
    results = []
    for role in ROLES:
        strike = float(atm + role * step)
        instrument = identity.get((side, strike))
        base = dict(session_date=session.session_date, trade_index=trade_index, direction=direction,
                    strategy_entry_time=trade["entry_time"], strategy_exit_time=trade["exit_time"],
                    strategy_exit_reason=trade.get("exit_reason"), entry_spot=spot,
                    expiry=session.expiry, side=side, atm=atm, role=role,
                    strike=strike, instrument_key=instrument,
                    research_entry_time=entry_at.isoformat(), research_exit_time=exit_at.isoformat())
        if not instrument:
            results.append(dict(base, status="INCOMPLETE", issue="EXACT_CONTRACT_MISSING"))
            continue
        series = index[(side, strike, instrument)]
        if any((side, strike, instrument, ts) in duplicates for ts in series):
            results.append(dict(base, status="INCOMPLETE", issue="DUPLICATE_OPTION_MINUTE"))
            continue
        if exit_at <= entry_at:
            results.append(dict(base, status="INCOMPLETE", issue="NONPOSITIVE_HOLDING_PERIOD"))
            continue
        expected = [entry_at + timedelta(minutes=n) for n in range(int((exit_at - entry_at).total_seconds() // 60) + 1)]
        missing = [ts for ts in expected if ts not in series]
        if missing:
            results.append(dict(base, status="INCOMPLETE", issue="MISSING_EXACT_MINUTE:" + missing[0].isoformat()))
            continue
        entry, exit_row = series[entry_at], series[exit_at]
        window = [series[ts] for ts in expected[:-1]]
        if entry.open <= 0 or exit_row.open <= 0 or any(c.open <= 0 or c.high < c.low for c in window):
            results.append(dict(base, status="INCOMPLETE", issue="INVALID_OPTION_PRICE"))
            continue
        points = float(exit_row.open - entry.open)
        results.append(dict(base, status="AVAILABLE", issue=None,
                            entry_open=float(entry.open), exit_open=float(exit_row.open),
                            gross_points=points, gross_return_pct=100 * points / float(entry.open),
                            mfe_points=max(float(c.high) for c in window) - float(entry.open),
                            mae_points=min(float(c.low) for c in window) - float(entry.open),
                            entry_volume=int(entry.volume), exit_volume=int(exit_row.volume)))
    return results


def summarize(rows: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    atm = {(r["session_date"], r["trade_index"]): r for r in rows if r["role"] == 0 and r["status"] == "AVAILABLE"}
    for row in rows:
        split = "TRAIN" if row["session_date"] <= "2026-07-13" else "VALIDATION"
        grouped[(split, row["direction"], row["role"])].append(row)
    out = []
    for (split, direction, role), group in sorted(grouped.items()):
        available = [row for row in group if row["status"] == "AVAILABLE"]
        paired = [(row, atm[(row["session_date"], row["trade_index"])]) for row in available
                  if (row["session_date"], row["trade_index"]) in atm]
        out.append(dict(split=split, direction=direction, role=role, trades=len(group), complete=len(available),
                        coverage_pct=100 * len(available) / len(group),
                        mean_gross_points=sum(row["gross_points"] for row in available) / len(available) if available else None,
                        mean_gross_return_pct=sum(row["gross_return_pct"] for row in available) / len(available) if available else None,
                        paired_with_atm=len(paired),
                        mean_gross_points_minus_atm=sum(row["gross_points"] - baseline["gross_points"] for row, baseline in paired) / len(paired) if paired else None,
                        gross_wins=sum(row["gross_points"] > 0 for row in available),
                        gross_losses=sum(row["gross_points"] < 0 for row in available)))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", type=Path, default=Path("data/historical-evidence/hilega-v2-alignment-dual-exit-v1"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--lag-minutes", type=int, default=1, choices=(0, 1))
    parser.add_argument("--from-date", default="2026-04-15")
    parser.add_argument("--through-date", default="2026-10-13")
    parser.add_argument("--expected-version", default="five-minute-setup-1.2.0-pending-switch")
    args = parser.parse_args()
    rows, days = [], []
    for path in sorted(args.replay_root.glob("????-??-??.json")):
        day = path.stem
        if not args.from_date <= day <= args.through_date:
            continue
        replay = json.loads(path.read_text(encoding="utf-8"))
        if replay.get("model") != REPLAY_MODEL or replay.get("strategy_id") != REPLAY_MODEL:
            raise ValueError(f"REPLAY_STRATEGY_MISMATCH:{path}")
        if replay.get("strategy_version") != args.expected_version:
            raise ValueError(f"REPLAY_VERSION_MISMATCH:{path}:{replay.get('strategy_version')}")
        trades = replay.get("trades") or []
        try:
            session = choose_option_ohlc_session(day, data_root=args.data_root)
        except Exception as exc:
            days.append(dict(session_date=day, trades=len(trades), status="OPTION_CACHE_UNAVAILABLE", issue=str(exc)))
            continue
        days.append(dict(session_date=day, trades=len(trades), status="CACHE_AVAILABLE", expiry=session.expiry))
        for index, trade in enumerate(trades, 1):
            rows.extend(compare_trade(trade, session, lag_minutes=args.lag_minutes, trade_index=index))
    print(json.dumps(dict(model="HILEGA_STRIKE_COMPARISON_RESEARCH_V1", strategy_id=STRATEGY,
                          selection_approved=False, order_enabled=False,
                          expected_strategy_version=args.expected_version,
                          price_semantics=f"EXACT_OPTION_MINUTE_OPEN_WITH_{args.lag_minutes}M_LAG_NOT_FILL",
                          days=days, summary=summarize(rows), legs=rows), indent=2, default=str))


if __name__ == "__main__":
    main()
