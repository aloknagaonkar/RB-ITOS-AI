from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from scripts.compare_proved_runner_exit_policies import compare_session_trade


DAY = "2026-09-29"
ENTRY_AT = f"{DAY}T09:26:00+05:30"


def event(kind, minute, price, result=None):
    return {
        "event_type": kind,
        "event_timestamp": f"{DAY}T{minute}:00+05:30",
        "session_date": DAY,
        "family": "E",
        "direction": "BEARISH",
        "underlying_price": price,
        "midpoint": 22670.825,
        "result": result,
    }


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


class ProvedRunnerPolicyComparisonTests(unittest.TestCase):
    def test_runner_strengthening_comparison_keeps_policies_separate(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audit = [
                event("E_ENTRY", "09:26", 22652.4),
                event("PLUS20_PROOF", "09:28", 22634.4),
                event(
                    "RUNNER_CLASSIFICATION",
                    "09:38",
                    22581.55,
                    "RUNNER_STRENGTHENING",
                ),
                event("DEGRADED_STARTED", "09:40", 22594.85),
                event("STRUCTURAL_TERMINAL", "11:13", 22687.35),
            ]
            timestamps = pd.date_range(
                f"{DAY}T09:15:00+05:30", periods=360, freq="min"
            )
            minutes = []
            for timestamp in timestamps:
                close = 22640.0
                low = 22630.0
                token = timestamp.strftime("%H:%M")
                if token == "09:38":
                    close, low = 22581.55, 22575.0
                elif token == "09:39":
                    close, low = 22590.0, 22589.0
                minutes.append(
                    {
                        "timestamp": timestamp.isoformat(),
                        "underlying_open": close,
                        "underlying_high": close + 2.0,
                        "underlying_low": low,
                        "underlying_close": close,
                    }
                )
            write_jsonl(root / DAY / "audit.jsonl", audit)
            write_jsonl(root / DAY / "minutes.jsonl", minutes)
            result = compare_session_trade(
                session_date=DAY,
                entry_timestamp=ENTRY_AT,
                replay_root=root,
            )
        self.assertEqual(
            result["three_tier_policy_status"],
            "COUNTERFACTUAL_ON_RUNNER_STRENGTHENING",
        )
        self.assertEqual(result["comparison_points"]["THREE_TIER"], 50.0)
        self.assertAlmostEqual(
            result["comparison_points"]["DEGRADED_EXIT"], 57.55
        )
        self.assertAlmostEqual(
            result["comparison_points"]["STRUCTURAL_BASELINE"], -34.95
        )
        self.assertEqual(result["best_observed_policy"], "DEGRADED_EXIT")
        self.assertFalse(result["safety"]["execution_enabled"])


if __name__ == "__main__":
    unittest.main()
