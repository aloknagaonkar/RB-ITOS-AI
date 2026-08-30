from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


BASE = Path("artifacts/red_bar/data/historical/upstox/NSE_INDEX_Nifty_50/1")
CALIBRATION = {
    "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"
}


def prepare(day: str) -> pd.DataFrame:
    frame = pd.read_csv(BASE / f"{day}.csv")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert("Asia/Kolkata")
    previous_close = frame["close"].shift()
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr"] = true_range.ewm(alpha=1 / 14, adjust=False).mean()
    frame["ema10"] = frame["close"].ewm(span=10, adjust=False).mean()
    frame["ema30"] = frame["close"].ewm(span=30, adjust=False).mean()
    frame["range"] = frame["high"] - frame["low"]
    frame["body"] = (frame["close"] - frame["open"]).abs()
    frame["body_ratio"] = frame["body"] / frame["range"].replace(0, np.nan)
    frame["close_location"] = (
        (frame["close"] - frame["low"]) / frame["range"].replace(0, np.nan)
    )
    frame["compression"] = (
        frame["range"].shift().rolling(5).mean()
        / frame["range"].shift().rolling(20).mean()
    )
    frame["twap"] = ((frame["high"] + frame["low"] + frame["close"]) / 3).expanding().mean()

    highs = frame["high"].to_numpy()
    lows = frame["low"].to_numpy()
    latest_high = latest_low = previous_high = np.nan
    confirmed_highs = np.full(len(frame), np.nan)
    confirmed_lows = np.full(len(frame), np.nan)
    previous_highs = np.full(len(frame), np.nan)
    for index in range(len(frame)):
        pivot = index - 2
        if pivot >= 2:
            high_window = highs[pivot - 2 : pivot + 3]
            low_window = lows[pivot - 2 : pivot + 3]
            if highs[pivot] == high_window.max() and np.sum(high_window == highs[pivot]) == 1:
                previous_high, latest_high = latest_high, highs[pivot]
            if lows[pivot] == low_window.min() and np.sum(low_window == lows[pivot]) == 1:
                latest_low = lows[pivot]
        confirmed_highs[index] = latest_high
        confirmed_lows[index] = latest_low
        previous_highs[index] = previous_high
    frame["pivot_high"] = confirmed_highs
    frame["pivot_low"] = confirmed_lows
    frame["previous_pivot_high"] = previous_highs

    five = frame.set_index("timestamp").resample(
        "5min", origin="start_day", offset="15min", label="left", closed="left"
    ).agg(close=("close", "last"), rows=("close", "count")).dropna()
    five = five[five["rows"] >= 5]
    five["ema10"] = five["close"].ewm(span=10, adjust=False).mean()
    five["bearish"] = (five["close"] < five["ema10"]) & ((five["ema10"] - five["ema10"].shift(2)) < 0)
    availability = {timestamp + pd.Timedelta(minutes=5): bool(value) for timestamp, value in five["bearish"].items()}
    state = False
    states = []
    for timestamp in frame["timestamp"]:
        if timestamp in availability:
            state = availability[timestamp]
        states.append(state)
    frame["five_minute_bearish"] = states
    return frame


def detect(frame: pd.DataFrame) -> list[dict[str, object]]:
    events = []
    last_event = -99
    for index in range(30, len(frame) - 2):
        if index - last_event < 10:
            continue
        row = frame.iloc[index]
        previous = frame.iloc[index - 1]
        if pd.isna(row["pivot_high"]) or pd.isna(row["pivot_low"]):
            continue
        compression = frame["compression"].iloc[max(20, index - 8) : index + 1].min()
        acceleration = frame["ema10"].iloc[index] - frame["ema10"].iloc[index - 2]
        momentum = frame["close"].iloc[index] - frame["close"].iloc[index - 3]
        common = (
            np.isfinite(compression)
            and compression <= 0.85
            and row["body_ratio"] >= 0.60
            and row["body"] / row["atr"] >= 0.50
        )
        bullish = (
            common
            and row["close"] > row["pivot_high"]
            and previous["close"] <= row["pivot_high"]
            and row["close"] > row["open"]
            and row["ema10"] > row["ema30"]
            and acceleration > 0
            and momentum > 0
            and row["close_location"] >= 0.75
            and (row["close"] - row["pivot_high"]) / row["atr"] >= 0.08
        )
        lower_high = (
            np.isfinite(row["previous_pivot_high"])
            and row["pivot_high"] < row["previous_pivot_high"]
        )
        bearish = (
            common
            and row["close"] < row["pivot_low"]
            and previous["close"] >= row["pivot_low"]
            and row["close"] < row["open"]
            and row["ema10"] < row["ema30"]
            and acceleration < 0
            and momentum < 0
            and row["close_location"] <= 0.25
            and (row["pivot_low"] - row["close"]) / row["atr"] >= 0.15
            and row["five_minute_bearish"]
            and frame["ema30"].iloc[index] - frame["ema30"].iloc[index - 3] < 0
            and lower_high
            and row["ema10"] - row["close"] <= 1.25 * row["atr"]
            and row["close"] < row["twap"]
            and row["timestamp"].time() < pd.Timestamp("14:45").time()
        )
        if bullish or bearish:
            events.append(
                {
                    "index": index,
                    "direction": "BULLISH" if bullish else "BEARISH",
                    "trigger": row["pivot_high"] if bullish else row["pivot_low"],
                    "low": row["low"],
                    "high": row["high"],
                    "close": row["close"],
                }
            )
            last_event = index
    return events


def backtest(frame: pd.DataFrame, events: list[dict[str, object]]) -> list[dict[str, object]]:
    trades = []
    available = 0
    for event in events:
        index = int(event["index"])
        direction = str(event["direction"])
        trigger = float(event["trigger"])
        if index < available:
            continue
        if direction == "BULLISH":
            entry_index = index
            entry = float(event["close"])
        else:
            entry_index = None
            entry = 0.0
            for candidate_index in (index + 1, index + 2):
                row = frame.iloc[candidate_index]
                if (
                    row["close"] < trigger
                    and row["close"] < row["ema10"]
                    and row["high"] <= trigger + 0.35 * row["atr"]
                ):
                    entry_index = candidate_index
                    entry = float(row["close"])
                    break
            if entry_index is None:
                continue
        stop = float(event["low"] if direction == "BULLISH" else event["high"])
        risk = entry - stop if direction == "BULLISH" else stop - entry
        if not 5 <= risk <= 35:
            continue
        target = entry + 2 * risk if direction == "BULLISH" else entry - 2 * risk
        exit_price = float(frame["close"].iloc[-1])
        exit_reason = "EOD"
        exit_index = len(frame) - 1
        for candle_index in range(entry_index + 1, len(frame)):
            row = frame.iloc[candle_index]
            hit_stop = row["low"] <= stop if direction == "BULLISH" else row["high"] >= stop
            hit_target = row["high"] >= target if direction == "BULLISH" else row["low"] <= target
            if hit_stop:  # conservative same-candle precedence
                exit_price, exit_reason, exit_index = stop, "STOP", candle_index
                break
            if hit_target:
                exit_price, exit_reason, exit_index = target, "TARGET", candle_index
                break
        points = exit_price - entry if direction == "BULLISH" else entry - exit_price
        trades.append(
            {
                "day": str(frame["timestamp"].iloc[0].date()),
                "time": frame["timestamp"].iloc[entry_index].strftime("%H:%M"),
                "direction": direction,
                "entry": entry,
                "stop": stop,
                "target": target,
                "exit": exit_price,
                "reason": exit_reason,
                "points": points,
                "r_multiple": points / risk,
            }
        )
        available = exit_index + 1
    return trades


def print_report(name: str, trades: list[dict[str, object]]) -> None:
    gross_profit = sum(max(0.0, float(row["points"])) for row in trades)
    gross_loss = -sum(min(0.0, float(row["points"])) for row in trades)
    wins = sum(float(row["points"]) > 0 for row in trades)
    losses = sum(float(row["points"]) < 0 for row in trades)
    print(
        "SUMMARY", name, "trades", len(trades), "wins", wins, "losses", losses,
        "win_rate", round(100 * wins / len(trades), 1) if trades else 0,
        "gross_profit", round(gross_profit, 2), "gross_loss", round(gross_loss, 2),
        "net_points", round(gross_profit - gross_loss, 2),
        "net_R", round(sum(float(row["r_multiple"]) for row in trades), 2),
        "profit_factor", round(gross_profit / gross_loss, 3) if gross_loss else None,
    )
    for direction in ("BULLISH", "BEARISH"):
        selected = [row for row in trades if row["direction"] == direction]
        print(
            "DIRECTION", name, direction, "trades", len(selected),
            "wins", sum(float(row["points"]) > 0 for row in selected),
            "losses", sum(float(row["points"]) < 0 for row in selected),
            "net_points", round(sum(float(row["points"]) for row in selected), 2),
            "net_R", round(sum(float(row["r_multiple"]) for row in selected), 2),
        )


def main() -> None:
    all_trades = []
    for path in sorted(BASE.glob("*.csv")):
        frame = prepare(path.stem)
        events = detect(frame)
        trades = backtest(frame, events)
        for trade in trades:
            trade["sample"] = "CALIBRATION" if path.stem in CALIBRATION else "OUT_OF_SAMPLE"
        all_trades.extend(trades)
        print("DAY", path.stem, "events", len(events), "trades", len(trades))
    calibration = [row for row in all_trades if row["sample"] == "CALIBRATION"]
    out_of_sample = [row for row in all_trades if row["sample"] == "OUT_OF_SAMPLE"]
    print_report("CALIBRATION", calibration)
    print_report("OUT_OF_SAMPLE", out_of_sample)
    print_report("ALL", all_trades)
    print("OUT_OF_SAMPLE_TRADES")
    for row in out_of_sample:
        print(row)


if __name__ == "__main__":
    main()
