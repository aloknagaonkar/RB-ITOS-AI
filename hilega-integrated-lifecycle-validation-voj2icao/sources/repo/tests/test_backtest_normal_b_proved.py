from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from scripts.backtest_normal_b_proved import backtest_normal_b_proved


START = pd.Timestamp("2026-08-25T09:42:00+05:30")
ACTIVATION = START + pd.Timedelta(minutes=10)


def frame(periods: int = 50, direction: str = "BULLISH") -> pd.DataFrame:
    timestamps = pd.date_range(
        START + pd.Timedelta(minutes=1), periods=periods, freq="min"
    )
    if direction == "BULLISH":
        data = pd.DataFrame(
            {
                "Timestamp": timestamps,
                "Open": 124.0,
                "High": 125.0,
                "Low": 123.0,
                "Close": 124.0,
            }
        )
        excursion = data["High"].to_numpy() - 100.0
    else:
        data = pd.DataFrame(
            {
                "Timestamp": timestamps,
                "Open": 76.0,
                "High": 77.0,
                "Low": 75.0,
                "Close": 76.0,
            }
        )
        excursion = 100.0 - data["Low"].to_numpy()
    data["Intrabar_MFE"] = np.maximum.accumulate(np.maximum(excursion, 0.0))
    return data


def refresh_mfe(data: pd.DataFrame, direction: str = "BULLISH") -> pd.DataFrame:
    output = data.copy()
    excursion = (
        output["High"].to_numpy() - 100.0
        if direction == "BULLISH"
        else 100.0 - output["Low"].to_numpy()
    )
    output["Intrabar_MFE"] = np.maximum.accumulate(
        np.maximum(excursion, 0.0)
    )
    return output


def run(data: pd.DataFrame, direction: str = "BULLISH"):
    midpoint = 90.0 if direction == "BULLISH" else 110.0
    return backtest_normal_b_proved(
        refresh_mfe(data, direction),
        entry_timestamp=START,
        activation_timestamp=ACTIVATION,
        entry_price=100.0,
        midpoint_price=midpoint,
        direction=direction,
    )


class NormalBProvedBacktestTests(unittest.TestCase):
    def test_tier2_uses_actual_breach_close(self) -> None:
        data = frame()
        data.loc[10, ["Open", "High", "Low", "Close"]] = [128, 131, 127, 128]
        data.loc[11, ["Open", "High", "Low", "Close"]] = [114, 120, 110, 14 + 100]
        result, trace = run(data)
        self.assertEqual(result.exit_trigger, "Floor_Breach_Tier2")
        self.assertEqual(result.exit_price, 114.0)
        self.assertEqual(result.total_captured_points, 14.0)
        self.assertEqual(trace.iloc[-1]["Active_Floor_Points"], 15.0)

    def test_floor_equality_does_not_exit(self) -> None:
        data = frame()
        data.loc[10, ["Open", "High", "Low", "Close"]] = [115, 131, 114, 115]
        data.loc[11, ["Open", "High", "Low", "Close"]] = [114, 120, 113, 114]
        result, trace = run(data)
        self.assertEqual(result.exit_trigger, "Floor_Breach_Tier2")
        self.assertEqual(result.exit_timestamp, data.loc[11, "Timestamp"].isoformat())
        self.assertEqual(trace.iloc[-2]["Directional_Close_Points"], 15.0)

    def test_tier3_ratchet_never_decreases(self) -> None:
        data = frame()
        data.loc[10, ["Open", "High", "Low", "Close"]] = [140, 146, 139, 140]
        data.loc[11, ["Open", "High", "Low", "Close"]] = [144, 147, 143, 144]
        data.loc[12, ["Open", "High", "Low", "Close"]] = [138, 145, 137, 138]
        data.loc[13, ["Open", "High", "Low", "Close"]] = [133, 140, 132, 133]
        result, trace = run(data)
        self.assertEqual(result.exit_trigger, "Floor_Breach_Tier3")
        self.assertEqual(result.total_captured_points, 33.0)
        floors = trace["Active_Floor_Points"].dropna().to_numpy()
        self.assertTrue((np.diff(floors) >= 0).all())
        self.assertEqual(result.active_floor_points, 34.0)

    def test_target_is_exact_and_not_retroactive(self) -> None:
        data = frame()
        data.loc[9, ["Open", "High", "Low", "Close"]] = [145, 151, 140, 145]
        data.loc[10, ["Open", "High", "Low", "Close"]] = [145, 149, 140, 145]
        result, _ = run(data)
        self.assertNotEqual(result.exit_timestamp, ACTIVATION.isoformat())
        self.assertEqual(result.exit_trigger, "Floor_Breach_Tier3")

        data = frame()
        data.loc[10, ["Open", "High", "Low", "Close"]] = [145, 151, 140, 145]
        result, _ = run(data)
        self.assertEqual(result.exit_trigger, "Target_Hit")
        self.assertEqual(result.total_captured_points, 50.0)
        self.assertEqual(result.exit_price, 150.0)

    def test_inactivity_exits_on_following_exact_minute(self) -> None:
        result, trace = run(frame())
        expected = ACTIVATION + pd.Timedelta(minutes=31)
        self.assertEqual(result.exit_trigger, "Time_Stop")
        self.assertEqual(result.exit_timestamp, expected.isoformat())
        self.assertEqual(trace.iloc[-2]["Inactivity_Exit_Due"], expected.isoformat())

    def test_scheduled_time_stop_cannot_be_cancelled(self) -> None:
        data = frame()
        due_index = 40
        data.loc[due_index, ["Open", "High", "Low", "Close"]] = [128, 129, 127, 128]
        result, _ = run(data)
        self.assertEqual(result.exit_trigger, "Time_Stop")
        self.assertEqual(
            result.exit_timestamp, data.loc[due_index, "Timestamp"].isoformat()
        )

    def test_bearish_directional_points(self) -> None:
        data = frame(direction="BEARISH")
        data.loc[10, ["Open", "High", "Low", "Close"]] = [72, 73, 69, 72]
        data.loc[11, ["Open", "High", "Low", "Close"]] = [86, 90, 80, 86]
        result, _ = run(data, "BEARISH")
        self.assertEqual(result.exit_trigger, "Floor_Breach_Tier2")
        self.assertEqual(result.total_captured_points, 14.0)
        self.assertEqual(result.raw_exit_minus_entry, -14.0)

    def test_midpoint_backstop(self) -> None:
        data = frame()
        data.loc[10, ["Open", "High", "Low", "Close"]] = [95, 96, 89, 89]
        result, _ = run(data)
        self.assertEqual(result.exit_trigger, "Midpoint_Invalidation")
        self.assertEqual(result.exit_price, 89.0)

    def test_bad_supplied_mfe_is_rejected(self) -> None:
        data = frame()
        data["Intrabar_MFE"] = 99.0
        with self.assertRaisesRegex(ValueError, "Intrabar_MFE disagrees"):
            backtest_normal_b_proved(
                data,
                entry_timestamp=START,
                activation_timestamp=ACTIVATION,
                entry_price=100.0,
                midpoint_price=90.0,
                direction="BULLISH",
            )

    def test_future_rows_do_not_change_prefix(self) -> None:
        baseline = frame()
        _, short_trace = run(baseline.iloc[:20])
        changed = baseline.copy()
        changed.loc[25:, ["Open", "High", "Low", "Close"]] = [170, 180, 160, 170]
        _, long_trace = run(changed)
        columns = [
            "Timestamp",
            "Computed_MFE",
            "Candidate_State",
            "Active_Floor_Points",
            "Exit_Trigger",
        ]
        pd.testing.assert_frame_equal(
            short_trace[columns], long_trace.iloc[: len(short_trace)][columns]
        )

    def test_missing_minute_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "contiguous"):
            run(frame().drop(index=4))


if __name__ == "__main__":
    unittest.main()
